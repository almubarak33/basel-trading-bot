from datetime import date

import pytest

from app.sec_data import build_company_profile


def concept(value, unit="USD", *, annual=False):
    row = {"val": value, "end": "2025-12-31", "filed": "2026-02-20",
           "form": "10-K", "fp": "FY" if annual else "Q4"}
    return {"units": {unit: [row]}}


def test_company_profile_derives_fundamentals_and_links_filings():
    today = date.today().isoformat()
    submissions = {
        "name": "Example Technologies Inc.", "sic": "3571",
        "sicDescription": "Electronic Computers", "fiscalYearEnd": "1231",
        "stateOfIncorporation": "DE",
        "addresses": {"business": {"city": "Austin", "stateOrCountryDescription": "Texas"}},
        "filings": {"recent": {
            "form": ["4", "25-NSE", "10-K"],
            "filingDate": [today, today, "2026-02-20"],
            "reportDate": [today, today, "2025-12-31"],
            "accessionNumber": ["0000000001-26-000001", "0000000001-26-000002", "0000000001-26-000003"],
            "primaryDocument": ["form4.xml", "form25.htm", "annual.htm"],
        }},
    }
    facts = {"facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": concept(10_000_000, "shares"),
            "EntityPublicFloat": concept(42_000_000),
            "EntityNumberOfEmployees": concept(120, "employees"),
        },
        "us-gaap": {
            "Revenues": concept(100_000_000, annual=True),
            "NetIncomeLoss": concept(12_000_000, annual=True),
            "StockholdersEquity": concept(60_000_000),
            "Assets": concept(150_000_000),
            "Liabilities": concept(90_000_000),
            "EarningsPerShareDiluted": concept(1.2, "USD/shares", annual=True),
            "CommonStockDividendsPerShareDeclared": concept(0.2, "USD/shares", annual=True),
        },
    }}

    profile = build_company_profile(
        "EXM", 12.0, {"cik": 1, "name": "Example", "exchange": "NASDAQ"},
        submissions, facts,
    )

    fundamentals = profile["fundamentals"]
    assert fundamentals["market_cap_estimate"] == 120_000_000
    assert fundamentals["pe_estimate"] == pytest.approx(10)
    assert fundamentals["profit_margin_estimate"] == pytest.approx(12)
    assert fundamentals["roe_estimate"] == pytest.approx(20)
    assert profile["insider_filings_12m"]["count"] == 1
    assert profile["delisting_filings"][0]["form"] == "25-NSE"
    assert profile["recent_filings"][0]["url"].startswith("https://www.sec.gov/Archives/")
