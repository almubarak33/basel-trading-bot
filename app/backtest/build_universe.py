"""Build a backtest symbol universe from Alpaca's asset list.

    python -m app.backtest.build_universe --start 2024-01-02 --end 2024-03-28

Survivorship bias is the main threat to a momentum backtest on low-priced
stocks: the names that collapsed or were delisted are exactly the ones the
strategy runs into, and a universe built from today's active tickers silently
drops all of them. Alpaca lists inactive assets too, so `--include-inactive`
(the default) keeps them in.

The filter is applied on daily bars over the backtest window itself. That is
deliberate — it selects the names that were tradeable *during* the period, not
the ones that did well in it, so it does not leak future performance.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from ..config import settings
from ..indicators import num

DATA_URL = "https://data.alpaca.markets"
TRADING_URL = "https://paper-api.alpaca.markets"


def qualifies(bars: list[dict], min_price: float, max_price: float,
              min_dollar_volume: float, min_days: int) -> bool:
    """True when a symbol was inside the price band and liquid enough, often enough.

    Uses close × volume as the liquidity measure rather than share volume, since
    a million shares of a $2 stock and of a $30 stock are not comparable.
    """
    hits = 0
    for bar in bars:
        close, volume = num(bar.get("c")), num(bar.get("v"))
        if close <= 0 or volume <= 0:
            continue
        price_ok=close>=min_price and (max_price<=0 or close<=max_price)
        if price_ok and close * volume >= min_dollar_volume:
            hits += 1
            if hits >= min_days:
                return True
    return False


async def _fetch_assets(client: httpx.AsyncClient, include_inactive: bool) -> list[str]:
    symbols: set[str] = set()
    statuses = ["active", "inactive"] if include_inactive else ["active"]
    for status in statuses:
        response = await client.get(f"{TRADING_URL}/v2/assets",
                                    params={"status": status, "asset_class": "us_equity"})
        response.raise_for_status()
        for asset in response.json():
            # Exclude anything the broker will not let a backtest realistically trade.
            if not asset.get("tradable"):
                continue
            symbol = (asset.get("symbol") or "").upper()
            if symbol and symbol.isalpha():   # skip warrants/units/rights suffixes
                symbols.add(symbol)
    return sorted(symbols)


async def _fetch_daily(client: httpx.AsyncClient, symbols: list[str],
                       start: date, end: date, batch: int = 200) -> dict[str, list[dict]]:
    collected: dict[str, list[dict]] = defaultdict(list)
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i+batch]
        page_token = None
        while True:
            params = {"symbols": ",".join(chunk), "timeframe": "1Day",
                      "start": start.isoformat(), "end": end.isoformat(),
                      "limit": 10000, "adjustment": "raw", "feed": "sip"}
            if page_token:
                params["page_token"] = page_token
            response = await client.get(f"{DATA_URL}/v2/stocks/bars", params=params)
            response.raise_for_status()
            payload = response.json()
            for symbol, bars in (payload.get("bars") or {}).items():
                collected[symbol].extend(bars)
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        print(f"  … scanned {min(i+batch, len(symbols)):,}/{len(symbols):,} symbols", flush=True)
    return collected


async def build(start: date, end: date, min_price: float, max_price: float,
                min_dollar_volume: float, min_days: int, include_inactive: bool,
                limit: int | None) -> list[str]:
    if not (settings.api_key and settings.api_secret):
        raise SystemExit("ALPACA_API_KEY / ALPACA_API_SECRET are required.")
    headers = {"APCA-API-KEY-ID": settings.api_key, "APCA-API-SECRET-KEY": settings.api_secret}

    async with httpx.AsyncClient(timeout=90, headers=headers) as client:
        print("Fetching asset list…", flush=True)
        candidates = await _fetch_assets(client, include_inactive)
        print(f"  {len(candidates):,} tradable US equities", flush=True)

        print("Scanning daily bars…", flush=True)
        daily = await _fetch_daily(client, candidates, start, end)

    kept = [s for s, bars in daily.items()
            if qualifies(bars, min_price, max_price, min_dollar_volume, min_days)]
    kept.sort()
    if limit:
        # Keep the most liquid names when trimming, not an alphabetical slice.
        kept.sort(key=lambda s: sum(num(b.get("c")) * num(b.get("v")) for b in daily[s]), reverse=True)
        kept = sorted(kept[:limit])
    return kept


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", required=True, type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    parser.add_argument("--end", required=True, type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    parser.add_argument("--min-price", type=float, default=settings.min_price)
    parser.add_argument("--max-price", type=float, default=settings.max_price)
    parser.add_argument("--min-dollar-volume", type=float, default=5_000_000,
                        help="Minimum close x volume on a qualifying day (default 5M)")
    parser.add_argument("--min-days", type=int, default=5,
                        help="Qualifying days required to keep the symbol (default 5)")
    parser.add_argument("--include-inactive", action="store_true", default=True,
                        help="Keep delisted names — on by default, they carry the losses")
    parser.add_argument("--survivors-only", dest="include_inactive", action="store_false",
                        help="Drop delisted names; introduces survivorship bias")
    parser.add_argument("--limit", type=int, help="Cap the universe to the N most liquid names")
    parser.add_argument("--out", type=Path, default=Path("universe.txt"))
    args = parser.parse_args(argv)

    symbols = asyncio.run(build(args.start, args.end, args.min_price, args.max_price,
                                args.min_dollar_volume, args.min_days,
                                args.include_inactive, args.limit))
    args.out.write_text("\n".join(symbols) + "\n")
    print(f"\n{len(symbols):,} symbols written to {args.out}")
    if not args.include_inactive:
        print("WARNING: delisted names excluded — results will look better than reality.")
    return symbols


if __name__ == "__main__":
    main()
