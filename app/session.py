"""Regular US equity session helpers, shared by the live bot and the backtester.

The backtester passes a simulated clock; live code passes datetime.now(NY).
"""
from __future__ import annotations
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
MIN_SESSION_FRACTION = 0.05


def session_bounds(moment: datetime) -> tuple[datetime, datetime]:
    day = moment.astimezone(NY).date()
    return (datetime.combine(day, MARKET_OPEN, tzinfo=NY),
            datetime.combine(day, MARKET_CLOSE, tzinfo=NY))


def session_fraction(now: datetime) -> float:
    """How far into the regular session we are, used to scale expected volume."""
    now = now.astimezone(NY)
    open_dt, close_dt = session_bounds(now)
    if now <= open_dt: return MIN_SESSION_FRACTION
    if now >= close_dt: return 1.0
    elapsed = (now - open_dt).total_seconds() / (close_dt - open_dt).total_seconds()
    return max(MIN_SESSION_FRACTION, min(1.0, elapsed))


def opening_delay_active(now: datetime, minutes: int) -> bool:
    """True during the post-open window where entries are suppressed."""
    now = now.astimezone(NY)
    open_dt, _ = session_bounds(now)
    return open_dt <= now < open_dt + timedelta(minutes=minutes)
