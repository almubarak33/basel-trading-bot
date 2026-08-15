"""Helpers for presenting completed market sessions on stock charts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .indicators import num
from .session import MARKET_CLOSE, NY


def _timestamp(value) -> datetime | None:
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def completed_session_closes(bars: list[dict], now: datetime | None = None,
                             limit: int = 5) -> list[dict]:
    """Return the latest completed daily closes, newest first."""
    reference = (now or datetime.now(NY)).astimezone(NY)
    cutoff = reference.date() if reference.time() >= MARKET_CLOSE else reference.date() - timedelta(days=1)
    by_day: dict = {}
    for bar in bars or []:
        moment = _timestamp(bar.get("t"))
        close = num(bar.get("c"))
        if moment is None or close <= 0:
            continue
        session_day = moment.astimezone(NY).date()
        if session_day <= cutoff:
            by_day[session_day] = round(close, 4)
    return [
        {"date": day.isoformat(), "close": by_day[day]}
        for day in sorted(by_day, reverse=True)[:max(1, limit)]
    ]
