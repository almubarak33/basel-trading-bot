from __future__ import annotations
from dataclasses import dataclass
from .config import settings

@dataclass
class Candidate:
    symbol: str
    price: float
    change_pct: float
    volume_rank: int
    spread_pct: float
    above_vwap_proxy: bool
    breakout_proxy: bool
    score: float
    eligible: bool
    reasons: list[str]

def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

def build_candidate(symbol: str, change_pct: float, volume_rank: int, snapshot: dict) -> Candidate:
    latest_trade = snapshot.get("latestTrade") or {}
    latest_quote = snapshot.get("latestQuote") or {}
    minute = snapshot.get("minuteBar") or {}
    daily = snapshot.get("dailyBar") or {}
    prev = snapshot.get("prevDailyBar") or {}
    price = _num(latest_trade.get("p") or minute.get("c") or daily.get("c"))
    bid = _num(latest_quote.get("bp"))
    ask = _num(latest_quote.get("ap"))
    spread_pct = ((ask - bid) / ((ask + bid) / 2) * 100) if ask > 0 and bid > 0 and ask >= bid else 999.0
    day_open = _num(daily.get("o"))
    prev_high = _num(prev.get("h"))
    above_vwap_proxy = day_open > 0 and price >= day_open
    breakout_proxy = prev_high > 0 and price >= prev_high
    score = 0.0
    reasons = []
    score += min(max(change_pct, 0) / 20 * 30, 30)
    if change_pct >= settings.min_change_pct:
        reasons.append(f"Momentum +{change_pct:.1f}%")
    score += max(0, 26 - min(volume_rank, 26))
    if volume_rank <= 10:
        reasons.append(f"Top-volume rank #{volume_rank}")
    if spread_pct <= 0.25:
        score += 15
    elif spread_pct <= settings.max_spread_pct:
        score += 10
    if spread_pct <= settings.max_spread_pct:
        reasons.append(f"Spread {spread_pct:.2f}%")
    if above_vwap_proxy:
        score += 15
        reasons.append("Above session open proxy")
    if breakout_proxy:
        score += 15
        reasons.append("Above previous-day high")
    score = round(min(score, 100), 1)
    eligible = (
        settings.min_price <= price <= settings.max_price
        and change_pct >= settings.min_change_pct
        and spread_pct <= settings.max_spread_pct
        and score >= settings.min_score
    )
    return Candidate(symbol, price, change_pct, volume_rank, round(spread_pct, 3), above_vwap_proxy, breakout_proxy, score, eligible, reasons)

def position_size(equity: float, entry: float, stop: float) -> int:
    if equity <= 0 or entry <= 0 or stop <= 0 or stop >= entry:
        return 0
    risk_dollars = equity * settings.risk_per_trade
    per_share = entry - stop
    raw = int(risk_dollars / per_share)
    cap = int((equity * 0.20) / entry)
    return max(0, min(raw, cap))
