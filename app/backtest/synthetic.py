"""Deterministic synthetic market data.

Lets the backtester (and its tests) run end-to-end with no API keys and no
network. Useful for validating the machinery — never for judging the strategy,
since the price paths are constructed rather than observed.
"""
from __future__ import annotations
import random
from datetime import date, datetime, timedelta, timezone

from ..session import MARKET_OPEN, NY
from .data import BarStore

BARS_PER_SESSION = 390


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _session_start(day: date) -> datetime:
    return datetime.combine(day, MARKET_OPEN, tzinfo=NY)


def _bars_from_path(day: date, prices: list[float], volumes: list[float]) -> list[dict]:
    start = _session_start(day)
    bars = []
    previous = prices[0]
    for i, (close, volume) in enumerate(zip(prices, volumes)):
        moment = start + timedelta(minutes=i)
        open_price = previous
        high = max(open_price, close) * 1.0008
        low = min(open_price, close) * 0.9992
        bars.append({
            "t": _iso(moment),
            "o": round(open_price, 4), "h": round(high, 4),
            "l": round(low, 4), "c": round(close, 4), "v": round(volume),
        })
        previous = close
    return bars


def _segment(start_value: float, end_value: float, count: int, rng: random.Random, noise: float) -> list[float]:
    if count <= 0:
        return []
    step = (end_value - start_value) / count
    return [start_value + step * (i + 1) + rng.uniform(-noise, noise) * start_value for i in range(count)]


def momentum_session(day: date, prior_close: float, rng: random.Random,
                     gap_pct: float = 8.0, base_volume: float = 40_000) -> list[dict]:
    """A gap-up that trends, pulls back toward VWAP, then reclaims on volume."""
    open_price = prior_close * (1 + gap_pct/100)
    peak = open_price * 1.035
    trough = open_price * 1.012
    reclaim = open_price * 1.030

    prices = ([open_price]
              + _segment(open_price, peak, 120, rng, 0.0008)
              + _segment(peak, trough, 60, rng, 0.0006)
              + _segment(trough, reclaim, 40, rng, 0.0006))
    prices += _segment(prices[-1], reclaim * 1.02, BARS_PER_SESSION - len(prices), rng, 0.0008)
    prices = prices[:BARS_PER_SESSION]

    volumes = []
    for i in range(len(prices)):
        weight = 3.0 if i < 20 else (1.6 if i > 180 else 1.0)
        volumes.append(base_volume * weight * rng.uniform(0.85, 1.15))
    return _bars_from_path(day, prices, volumes)


def drifting_session(day: date, prior_close: float, rng: random.Random,
                     drift_pct: float = 0.4, base_volume: float = 20_000) -> list[dict]:
    """An unremarkable session that should not produce a signal."""
    prices = [prior_close]
    for _ in range(BARS_PER_SESSION - 1):
        prices.append(prices[-1] * (1 + rng.gauss(drift_pct/100/BARS_PER_SESSION, 0.0009)))
    volumes = [base_volume * rng.uniform(0.8, 1.2) for _ in prices]
    return _bars_from_path(day, prices, volumes)


def trending_index_session(day: date, prior_close: float, rng: random.Random) -> list[dict]:
    """A healthy index session so the regime gate allows longs."""
    prices = _segment(prior_close, prior_close * 1.006, BARS_PER_SESSION, rng, 0.0002)
    volumes = [1_000_000 * rng.uniform(0.9, 1.1) for _ in prices]
    return _bars_from_path(day, prices, volumes)


def _daily_bar(day: date, close: float, volume: float) -> dict:
    return {"t": _iso(_session_start(day)), "o": close, "h": close, "l": close, "c": close, "v": volume}


def build_store(days: list[date], momentum_symbols: dict[str, float],
                quiet_symbols: dict[str, float] | None = None,
                seed: int = 7, warmup_days: int = 25,
                avg_daily_volume: float = 3_000_000) -> BarStore:
    """Assemble a replayable store: movers, quiet names, and the SPY/QQQ benchmarks.

    `avg_daily_volume` seeds the 20-day average that RVOL is measured against;
    keeping it well above the synthetic intraday volume is what makes the
    momentum names screen as unusually active.
    """
    rng = random.Random(seed)
    store = BarStore()
    quiet_symbols = quiet_symbols or {}
    first_day = days[0]
    warmup = [first_day - timedelta(days=i) for i in range(warmup_days, 0, -1)]

    for symbol, prior_close in {**momentum_symbols, **quiet_symbols}.items():
        daily = [_daily_bar(d, prior_close, avg_daily_volume) for d in warmup]
        for day in days:
            bars = (momentum_session(day, prior_close, rng) if symbol in momentum_symbols
                    else drifting_session(day, prior_close, rng))
            store.add_minute_bars(symbol, bars)
            close = float(bars[-1]["c"])
            daily.append(_daily_bar(day, close, avg_daily_volume))
        store.add_daily_bars(symbol, daily)

    for symbol, prior_close in (("SPY", 500.0), ("QQQ", 430.0)):
        daily = [_daily_bar(d, prior_close, 50_000_000) for d in warmup]
        for day in days:
            bars = trending_index_session(day, prior_close, rng)
            store.add_minute_bars(symbol, bars)
            daily.append(_daily_bar(day, float(bars[-1]["c"]), 50_000_000))
        store.add_daily_bars(symbol, daily)

    return store
