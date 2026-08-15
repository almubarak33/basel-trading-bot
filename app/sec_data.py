"""SEC EDGAR company metadata and XBRL fundamentals with honest fallbacks."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from .async_cache import AsyncTTLCache
from .config import settings

SEC_FILES = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
_CACHE = AsyncTTLCache()


async def _get(url: str) -> dict:
    headers = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


async def _ticker_index() -> dict[str, dict]:
    async def load():
        payload = await _get(SEC_FILES)
        fields = payload.get("fields") or []
        return {
            str(dict(zip(fields, row)).get("ticker") or "").upper(): dict(zip(fields, row))
            for row in payload.get("data") or []
            if isinstance(row, list)
        }
    return await _CACHE.get("sec:ticker-index", 12 * 60 * 60, load)


def _fact(payload: dict, tags: list[str], units: list[str], annual: bool = False) -> dict | None:
    candidates = []
    for taxonomy in ("us-gaap", "ifrs-full", "dei"):
        concepts = (payload.get("facts") or {}).get(taxonomy) or {}
        for tag in tags:
            concept = concepts.get(tag) or {}
            available_units = concept.get("units") or {}
            for unit in units:
                for item in available_units.get(unit) or []:
                    if annual and (item.get("form") not in ANNUAL_FORMS or item.get("fp") != "FY"):
                        continue
                    try:
                        value = float(item.get("val"))
                    except (TypeError, ValueError):
                        continue
                    candidates.append({
                        "value": value, "period_end": item.get("end"),
                        "filed": item.get("filed"), "form": item.get("form"),
                        "unit": unit, "tag": tag,
                    })
    if not candidates:
        return None
    return max(candidates, key=lambda item: (str(item.get("period_end") or ""),
                                             str(item.get("filed") or "")))


def _recent_filings(submissions: dict, cik: str) -> list[dict]:
    recent = ((submissions.get("filings") or {}).get("recent") or {})
    size = max((len(value) for value in recent.values() if isinstance(value, list)), default=0)
    rows = []
    for index in range(size):
        row = {key: value[index] for key, value in recent.items()
               if isinstance(value, list) and index < len(value)}
        accession = str(row.get("accessionNumber") or "")
        document = str(row.get("primaryDocument") or "")
        if accession and document:
            row["url"] = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                          f"{accession.replace('-', '')}/{document}")
        rows.append(row)
    return rows


def build_company_profile(symbol: str, price: float, index_row: dict,
                          submissions: dict, facts: dict) -> dict:
    cik = str(index_row.get("cik") or index_row.get("cik_str") or "").zfill(10)
    shares = _fact(facts, ["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"],
                   ["shares"])
    public_float = _fact(facts, ["EntityPublicFloat"], ["USD"])
    revenue = _fact(facts, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                            "SalesRevenueNet", "Revenue"], ["USD"], annual=True)
    net_income = _fact(facts, ["NetIncomeLoss", "ProfitLoss"], ["USD"], annual=True)
    equity = _fact(facts, ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], ["USD"])
    assets = _fact(facts, ["Assets"], ["USD"])
    liabilities = _fact(facts, ["Liabilities"], ["USD"])
    eps = _fact(facts, ["EarningsPerShareDiluted", "EarningsPerShareBasic", "BasicEarningsLossPerShare"],
                ["USD/shares", "USD / shares"], annual=True)
    dividend = _fact(facts, ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"],
                     ["USD/shares", "USD / shares"], annual=True)
    employees = _fact(facts, ["EntityNumberOfEmployees"], ["employees", "number", "pure"])

    def value(item):
        return item.get("value") if item else None

    share_value, revenue_value = value(shares), value(revenue)
    income_value, equity_value = value(net_income), value(equity)
    eps_value, dividend_value = value(eps), value(dividend)
    market_cap = share_value * price if share_value and price > 0 else None
    filings = _recent_filings(submissions, cik)
    cutoff = date.today() - timedelta(days=365)
    insider = [row for row in filings if str(row.get("form") or "").split("/")[0] in {"3", "4", "5"}
               and _date_at_least(row.get("filingDate"), cutoff)]
    delisting = [row for row in filings if str(row.get("form") or "").startswith("25")]
    business = (submissions.get("addresses") or {}).get("business") or {}
    return {
        "available": True, "source": "SEC EDGAR", "symbol": symbol.upper(), "cik": cik,
        "name": submissions.get("name") or index_row.get("name"),
        "exchange": index_row.get("exchange"), "sic": submissions.get("sic"),
        "industry": submissions.get("sicDescription"),
        "fiscal_year_end": submissions.get("fiscalYearEnd"),
        "state_of_incorporation": submissions.get("stateOfIncorporationDescription") or submissions.get("stateOfIncorporation"),
        "headquarters": {key: business.get(key) for key in ("city", "stateOrCountryDescription", "country") if business.get(key)},
        "former_names": submissions.get("formerNames") or [],
        "fundamentals": {
            "shares_outstanding": shares, "public_float_value": public_float,
            "market_cap_estimate": market_cap, "revenue": revenue, "net_income": net_income,
            "assets": assets, "liabilities": liabilities, "stockholders_equity": equity,
            "eps_annual": eps, "dividend_per_share_annual": dividend,
            "employees": employees,
            "pe_estimate": (price / eps_value) if eps_value and eps_value > 0 and price > 0 else None,
            "profit_margin_estimate": (income_value / revenue_value * 100) if revenue_value else None,
            "roe_estimate": (income_value / equity_value * 100) if equity_value else None,
            "dividend_yield_estimate": (dividend_value / price * 100) if dividend_value and price > 0 else None,
        },
        "insider_filings_12m": {"count": len(insider), "latest": insider[0] if insider else None},
        "delisting_filings": delisting[:3], "recent_filings": filings[:8],
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


def _date_at_least(value: Any, cutoff: date) -> bool:
    try:
        return date.fromisoformat(str(value)) >= cutoff
    except ValueError:
        return False


async def company_profile(symbol: str, price: float) -> dict:
    symbol = symbol.upper()
    try:
        index_row = (await _ticker_index()).get(symbol)
        if not index_row:
            return {"available": False, "source": "SEC EDGAR", "reason": "ticker_not_found"}
        cik = str(index_row.get("cik") or index_row.get("cik_str") or "").zfill(10)

        async def load():
            submissions, facts = await asyncio.gather(
                _get(SEC_SUBMISSIONS.format(cik=cik)),
                _get(SEC_FACTS.format(cik=cik)),
            )
            return build_company_profile(symbol, price, index_row, submissions, facts)
        return await _CACHE.get(f"sec:company:{symbol}", 6 * 60 * 60, load)
    except Exception as exc:
        return {"available": False, "source": "SEC EDGAR", "reason": type(exc).__name__}
