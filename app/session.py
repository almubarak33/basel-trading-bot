"""Regular US equity session helpers, shared by the live bot and the backtester.

The backtester passes a simulated clock; live code passes datetime.now(NY).
"""
from __future__ import annotations
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
# جلسات ممتدة: ما قبل الافتتاح وما بعد الإغلاق
PRE_MARKET_OPEN = time(4, 0)
AFTER_HOURS_CLOSE = time(20, 0)
AFTER_HOURS_MINUTES = 240  # 16:00 → 20:00
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


def in_regular_session(now: datetime) -> bool:
    local = now.astimezone(NY).time()
    return MARKET_OPEN <= local < MARKET_CLOSE


def in_after_hours(now: datetime) -> bool:
    local = now.astimezone(NY).time()
    return MARKET_CLOSE <= local < AFTER_HOURS_CLOSE


def in_pre_market(now: datetime) -> bool:
    local = now.astimezone(NY).time()
    return PRE_MARKET_OPEN <= local < MARKET_OPEN


def tradeable_now(now: datetime, market_open: bool, after_hours: bool, pre_market: bool) -> bool:
    """Whether the bot may work right now.

    `market_open` comes from the broker clock so holidays and half-days are the
    broker's calendar, not ours. The extended windows are only consulted on a
    day the market actually traded.
    """
    if market_open:
        return True
    if after_hours and in_after_hours(now):
        return True
    if pre_market and in_pre_market(now):
        return True
    return False


def session_end(now: datetime, after_hours: bool) -> datetime:
    """When the current trading day stops — the bell, or the extended close."""
    day = now.astimezone(NY).date()
    return datetime.combine(day, AFTER_HOURS_CLOSE if after_hours else MARKET_CLOSE, tzinfo=NY)


def minutes_until_day_end(next_close: str | None, after_hours: bool,
                          now: datetime | None = None) -> float | None:
    """Minutes left in the bot's trading day, extended session included.

    Before the bell the broker's `next_close` is the anchor, so half-days stay
    correct: a 13:00 close plus four extended hours ends the day at 17:00. Once
    past 16:00 that same field already points at tomorrow's bell, so the local
    extended close is the only boundary that means anything.
    """
    now = (now or datetime.now(NY)).astimezone(NY)
    if after_hours and in_after_hours(now):
        return (session_end(now, True) - now).total_seconds() / 60
    minutes = minutes_until(next_close, now)
    if minutes is None:
        return None
    return minutes + (AFTER_HOURS_MINUTES if after_hours else 0)
