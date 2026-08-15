"""Regular US equity session helpers, shared by the live bot and the backtester.

The backtester passes a simulated clock; live code passes datetime.now(NY).
"""
from __future__ import annotations
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
EXTENDED_OPEN = time(4, 0)
EXTENDED_CLOSE = time(20, 0)
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


def extended_scan_active(now: datetime) -> bool:
    """Premarket and after-hours discovery window; execution stays regular-hours only."""
    now = now.astimezone(NY)
    return now.weekday() < 5 and EXTENDED_OPEN <= now.time() < EXTENDED_CLOSE


def minutes_until_close(now: datetime) -> float:
    """Minutes left in a standard 16:00 session; negative once it has passed.

    Only correct for full sessions. Live code should prefer `minutes_until` with
    the broker's `next_close`, which also covers early-close days.
    """
    now = now.astimezone(NY)
    _, close_dt = session_bounds(now)
    return (close_dt - now).total_seconds() / 60


def minutes_until(timestamp: str | None, now: datetime | None = None) -> float | None:
    """Minutes from now until an ISO timestamp, or None if it cannot be read.

    Used with Alpaca's `next_close` so half-days — the market shutting at 13:00
    the day after Thanksgiving, for instance — are handled by the broker's own
    calendar rather than a hardcoded 16:00.
    """
    if not timestamp:
        return None
    try:
        moment = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=NY)
    reference = now or datetime.now(NY)
    return (moment - reference).total_seconds() / 60
