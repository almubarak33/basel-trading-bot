"""Historical bar storage, Alpaca fetching, and on-disk caching.

Bars keep Alpaca's wire shape ({"t","o","h","l","c","v"}) so they can be handed
straight to the production strategy code without translation.
"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from ..config import settings
from ..session import NY, MARKET_CLOSE, MARKET_OPEN

DATA_URL = "https://data.alpaca.markets"
DEFAULT_CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "bars"
BENCHMARKS = ("SPY", "QQQ")


def bar_time(bar: dict) -> datetime:
    """Parse a bar timestamp into an aware UTC datetime."""
    raw = bar["t"]
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def in_regular_session(moment: datetime) -> bool:
    local = moment.astimezone(NY)
    return MARKET_OPEN <= local.time() < MARKET_CLOSE


class BarStore:
    """Minute and daily bars indexed for point-in-time replay."""

    def __init__(self):
        # symbol -> session date -> ascending minute bars
        self.minute: dict[str, dict[date, list[dict]]] = defaultdict(lambda: defaultdict(list))
        # symbol -> ascending daily bars
        self.daily: dict[str, list[dict]] = defaultdict(list)

    def add_minute_bars(self, symbol: str, bars: list[dict]) -> None:
        for bar in bars:
            moment = bar_time(bar)
            if not in_regular_session(moment):
                continue
            self.minute[symbol][moment.astimezone(NY).date()].append(bar)
        for day_bars in self.minute[symbol].values():
            day_bars.sort(key=bar_time)

    def add_daily_bars(self, symbol: str, bars: list[dict]) -> None:
        self.daily[symbol] = sorted(bars, key=bar_time)

    def symbols(self) -> list[str]:
        return sorted(self.minute.keys())

    def sessions(self) -> list[date]:
        days: set[date] = set()
        for per_day in self.minute.values():
            days.update(per_day.keys())
        return sorted(days)

    def minute_bars(self, symbol: str, day: date) -> list[dict]:
        return self.minute.get(symbol, {}).get(day, [])

    def prior_daily_close(self, symbol: str, day: date) -> float:
        """Previous session's close — the reference for intraday % change."""
        prior = [b for b in self.daily.get(symbol, []) if bar_time(b).astimezone(NY).date() < day]
        return float(prior[-1].get("c") or 0) if prior else 0.0

    def trailing_daily_bars(self, symbol: str, day: date, count: int = 20) -> list[dict]:
        """Completed sessions strictly before `day` — never leaks the current day."""
        prior = [b for b in self.daily.get(symbol, []) if bar_time(b).astimezone(NY).date() < day]
        return prior[-count:]

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "minute": {s: {d.isoformat(): bars for d, bars in per_day.items()} for s, per_day in self.minute.items()},
            "daily": dict(self.daily),
        }
        path.write_text(json.dumps(payload))

    @classmethod
    def from_json(cls, path: Path) -> "BarStore":
        payload = json.loads(Path(path).read_text())
        store = cls()
        for symbol, per_day in payload.get("minute", {}).items():
            for day_iso, bars in per_day.items():
                store.minute[symbol][date.fromisoformat(day_iso)] = bars
        for symbol, bars in payload.get("daily", {}).items():
            store.daily[symbol] = bars
        return store


async def _fetch_paginated(client: httpx.AsyncClient, params: dict) -> dict[str, list[dict]]:
    """Alpaca caps each bars response, so follow next_page_token to completion."""
    collected: dict[str, list[dict]] = defaultdict(list)
    page_token = None
    while True:
        query = dict(params)
        if page_token:
            query["page_token"] = page_token
        response = await client.get(f"{DATA_URL}/v2/stocks/bars", params=query)
        response.raise_for_status()
        payload = response.json()
        for symbol, bars in (payload.get("bars") or {}).items():
            collected[symbol].extend(bars)
        page_token = payload.get("next_page_token")
        if not page_token:
            return collected


async def fetch_history(symbols: list[str], start: date, end: date,
                        cache_dir: Path | None = None, batch_size: int = 20) -> BarStore:
    """Download minute + daily bars for `symbols` plus the SPY/QQQ benchmarks."""
    if not (settings.api_key and settings.api_secret):
        raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET are required to download history.")

    cache_dir = cache_dir or DEFAULT_CACHE
    cache_file = Path(cache_dir) / f"{start.isoformat()}_{end.isoformat()}_{len(symbols)}syms.json"
    if cache_file.exists():
        return BarStore.from_json(cache_file)

    wanted = list(dict.fromkeys([s.upper() for s in symbols] + list(BENCHMARKS)))
    store = BarStore()
    headers = {"APCA-API-KEY-ID": settings.api_key, "APCA-API-SECRET-KEY": settings.api_secret}
    # Daily history needs a run-up before `start` so the 20-day volume average is
    # populated on the very first session of the backtest.
    daily_start = start - timedelta(days=60)
    end_exclusive = end + timedelta(days=1)

    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        for i in range(0, len(wanted), batch_size):
            batch = wanted[i:i+batch_size]
            common = {"symbols": ",".join(batch), "limit": 10000, "adjustment": "raw", "feed": "sip"}
            minute = await _fetch_paginated(client, {
                **common, "timeframe": "1Min",
                "start": start.isoformat(), "end": end_exclusive.isoformat(),
            })
            daily = await _fetch_paginated(client, {
                **common, "timeframe": "1Day",
                "start": daily_start.isoformat(), "end": end_exclusive.isoformat(),
            })
            for symbol in batch:
                store.add_minute_bars(symbol, minute.get(symbol, []))
                store.add_daily_bars(symbol, daily.get(symbol, []))

    store.to_json(cache_file)
    return store
