"""Pure indicator + regime helpers shared by the live bot and the backtester.

Keeping these free of IO is what lets the backtester replay the *exact* logic the
live engine runs, instead of a reimplementation that can silently drift.
"""
from __future__ import annotations


def num(v, default: float = 0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return default


def ema(values: list[float], length: int) -> float:
    if not values: return 0.0
    k = 2 / (length + 1); result = values[0]
    for v in values[1:]: result = v * k + result * (1-k)
    return result


def vwap(bars: list[dict]) -> float:
    pv = vol = 0.0
    for b in bars:
        v = num(b.get("v"))
        if v <= 0: continue
        typical = (num(b.get("h")) + num(b.get("l")) + num(b.get("c"))) / 3
        pv += typical * v; vol += v
    return pv / vol if vol else 0.0


def compute_regime(bars_by_symbol: dict[str, list[dict]]) -> dict:
    """SPY/QQQ trend health. Longs are allowed when at least one index is healthy."""
    details = {}; positive = 0
    for symbol in ("SPY", "QQQ"):
        rows = bars_by_symbol.get(symbol, [])
        closes = [num(b.get("c")) for b in rows if num(b.get("c")) > 0]
        if len(closes) < 20:
            details[symbol] = {"healthy": False, "reason": "insufficient_data"}; continue
        e9, e20 = ema(closes[-60:], 9), ema(closes[-80:], 20); last = closes[-1]
        ret15 = (last/closes[-16]-1)*100 if len(closes) >= 16 else 0
        healthy = last > e20 and e9 >= e20 and ret15 > -0.35; positive += int(healthy)
        details[symbol] = {"price": round(last,4), "ema9": round(e9,4), "ema20": round(e20,4), "ret15_pct": round(ret15,2), "healthy": healthy}
    return {"longs_allowed": positive >= 1, "healthy_indexes": positive, "details": details}
