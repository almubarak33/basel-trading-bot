"""Point-in-time reconstruction of the live screener.

The live bot calls Alpaca's `movers` and `most-actives` endpoints, which only
report *current* state and have no historical equivalent. To replay a past
session we rebuild the same two rankings from minute bars using strictly the
data that existed at the scan timestamp — never the day's final close.
"""
from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime

from .config import ExecutionModel
from .data import BarStore, bar_time

# Live requests 300 minutes of intraday history per scan.
INTRADAY_WINDOW_BARS = 300


@dataclass
class DaySlice:
    """One symbol's session, sliceable at any timestamp without rescanning."""
    symbol: str
    bars: list[dict]
    times: list[datetime]
    cumulative_volume: list[float]
    prior_close: float

    @classmethod
    def build(cls, symbol: str, bars: list[dict], prior_close: float) -> "DaySlice":
        times = [bar_time(b) for b in bars]
        cumulative, running = [], 0.0
        for bar in bars:
            running += float(bar.get("v") or 0)
            cumulative.append(running)
        return cls(symbol, bars, times, cumulative, prior_close)

    def index_at(self, moment: datetime) -> int:
        """Index of the last bar that had closed at `moment`, or -1."""
        return bisect_right(self.times, moment) - 1

    def window(self, index: int) -> list[dict]:
        return self.bars[max(0, index - INTRADAY_WINDOW_BARS + 1): index + 1]

    def price_at(self, index: int) -> float:
        return float(self.bars[index].get("c") or 0)

    def change_pct_at(self, index: int) -> float:
        if self.prior_close <= 0:
            return 0.0
        return (self.price_at(index) / self.prior_close - 1) * 100

    def volume_at(self, index: int) -> float:
        return self.cumulative_volume[index]


def build_snapshot(day_slice: DaySlice, index: int, execution: ExecutionModel) -> dict:
    """Synthesise the snapshot payload `build_candidate` expects.

    Minute bars carry no quotes, so the bid/ask is *estimated* from tick size:
    thinly-priced momentum names trade a cent or two wide, which dominates the
    percentage spread. This is the least faithful part of the replay and the
    spread filter should be read as approximate.
    """
    bar = day_slice.bars[index]
    price = float(bar.get("c") or 0)
    spread_pct = max(execution.min_spread_pct,
                     (execution.tick_size * execution.spread_ticks) / price * 100) if price > 0 else 999.0
    half = price * (spread_pct / 100) / 2
    return {
        "latestTrade": {"p": price, "t": bar.get("t")},
        "latestQuote": {"bp": round(price - half, 4), "ap": round(price + half, 4), "t": bar.get("t")},
        "minuteBar": bar,
        "dailyBar": {"c": price},
    }


class UniverseBuilder:
    """Rebuilds the gainers / most-actives screener for a single session."""

    def __init__(self, store: BarStore, day: date, symbols: list[str], screener_top: int):
        self.screener_top = screener_top
        self.slices: dict[str, DaySlice] = {}
        for symbol in symbols:
            bars = store.minute_bars(symbol, day)
            if not bars:
                continue
            self.slices[symbol] = DaySlice.build(symbol, bars, store.prior_daily_close(symbol, day))

    def select(self, moment: datetime, legacy_screener_change: bool = False) -> tuple[list[str], dict[str, float], dict[str, int], dict[str, int]]:
        """Return (symbols, change_map, active_rank, bar_index) as of `moment`.

        Mirrors the live ordering: gainers first, then most-actives that are not
        already present, capped the same way.
        """
        live: dict[str, int] = {}
        for symbol, day_slice in self.slices.items():
            index = day_slice.index_at(moment)
            if index >= 0:
                live[symbol] = index

        gainers = sorted((s for s in live if self.slices[s].change_pct_at(live[s]) > 0),
                         key=lambda s: self.slices[s].change_pct_at(live[s]), reverse=True)[:self.screener_top]
        actives = sorted(live, key=lambda s: self.slices[s].volume_at(live[s]), reverse=True)[:self.screener_top]

        symbols, change_map = [], {}
        for symbol in gainers:
            symbols.append(symbol)
            change_map[symbol] = self.slices[symbol].change_pct_at(live[symbol])
        for symbol in actives:
            if symbol in change_map:
                continue
            symbols.append(symbol)
            # Live derives this from the snapshot's previous close; the legacy
            # hardcoded 0.0 failed MIN_CHANGE_PCT and made the most-actives half
            # of the screener unreachable.
            change_map[symbol] = 0.0 if legacy_screener_change else self.slices[symbol].change_pct_at(live[symbol])

        symbols = symbols[:max(self.screener_top, 25)]
        active_rank = {symbol: i for i, symbol in enumerate(actives, 1)}
        return symbols, change_map, active_rank, live
