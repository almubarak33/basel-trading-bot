"""Point-in-time market-data validation for automated order decisions.

Discovery may keep showing a symbol when its feed is degraded, but automated
execution must never rely on stale, crossed, malformed, or internally
inconsistent data.  The backtester uses the same validator with its replay
timestamp so the gate is exercised outside production too.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and value > 0:
        raw = float(value)
        if raw > 1e17:
            raw /= 1_000_000_000
        elif raw > 1e14:
            raw /= 1_000_000
        elif raw > 1e11:
            raw /= 1_000
        try:
            parsed = datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, observed_at: datetime) -> float | None:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return None
    return (observed_at.astimezone(timezone.utc) - timestamp).total_seconds()


def assess_market_data(
    snapshot: dict,
    bars: list[dict],
    *,
    observed_at: datetime | None = None,
    max_quote_age_seconds: int = 90,
    max_bar_age_seconds: int = 180,
) -> dict:
    """Return a transparent execution gate and diagnostics for one symbol."""
    snapshot = snapshot or {}
    bars = bars or []
    trade = snapshot.get("latestTrade") or {}
    quote = snapshot.get("latestQuote") or {}
    minute = snapshot.get("minuteBar") or (bars[-1] if bars else {})
    price = _number(trade.get("p") or minute.get("c"))
    bid, ask = _number(quote.get("bp")), _number(quote.get("ap"))
    blockers: list[str] = []
    warnings: list[str] = []

    if price <= 0:
        blockers.append("missing_trade_price")
    if bid <= 0 or ask <= 0:
        blockers.append("missing_nbbo_quote")
    elif ask < bid:
        blockers.append("crossed_quote")

    malformed_bars = 0
    previous_time: datetime | None = None
    for bar in bars[-20:]:
        o, h, low, c = (_number(bar.get(key)) for key in ("o", "h", "l", "c"))
        if min(o, h, low, c) <= 0 or h < max(o, c, low) or low > min(o, c, h):
            malformed_bars += 1
        timestamp = parse_timestamp(bar.get("t"))
        if timestamp is not None and previous_time is not None and timestamp < previous_time:
            blockers.append("non_monotonic_bars")
            break
        if timestamp is not None:
            previous_time = timestamp
    if malformed_bars:
        blockers.append("malformed_ohlc")
    if not bars:
        blockers.append("missing_intraday_bars")

    spread_pct = 999.0
    if ask >= bid > 0:
        midpoint = (ask + bid) / 2
        spread_pct = (ask - bid) / midpoint * 100 if midpoint > 0 else 999.0
        divergence_pct = abs(price / midpoint - 1) * 100 if price > 0 and midpoint > 0 else 999.0
        allowed_divergence = max(3.0, spread_pct * 3)
        if divergence_pct > allowed_divergence:
            blockers.append("trade_quote_divergence")
    else:
        divergence_pct = None

    quote_age = trade_age = bar_age = None
    if observed_at is not None:
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        quote_age = _age_seconds(quote.get("t"), observed_at)
        trade_age = _age_seconds(trade.get("t"), observed_at)
        bar_age = _age_seconds(minute.get("t") or (bars[-1].get("t") if bars else None), observed_at)
        if quote_age is None or trade_age is None:
            blockers.append("missing_realtime_timestamp")
        else:
            if quote_age < -5 or trade_age < -5:
                blockers.append("future_market_timestamp")
            if quote_age > max_quote_age_seconds or trade_age > max_quote_age_seconds:
                blockers.append("stale_realtime_data")
        if bar_age is None:
            blockers.append("missing_bar_timestamp")
        elif bar_age < -5 or bar_age > max_bar_age_seconds:
            blockers.append("stale_intraday_bar")

    # Preserve deterministic ordering while removing duplicates.
    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    score = max(0, 100 - len(blockers) * 30 - len(warnings) * 8)
    return {
        "status": "BLOCKED" if blockers else ("DEGRADED" if warnings else "GOOD"),
        "score": score,
        "execution_allowed": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "metrics": {
            "quote_age_seconds": round(quote_age, 1) if quote_age is not None else None,
            "trade_age_seconds": round(trade_age, 1) if trade_age is not None else None,
            "bar_age_seconds": round(bar_age, 1) if bar_age is not None else None,
            "spread_pct": round(spread_pct, 4),
            "trade_quote_divergence_pct": round(divergence_pct, 4) if divergence_pct is not None else None,
            "bars_checked": min(len(bars), 20),
            "malformed_bars": malformed_bars,
        },
    }
