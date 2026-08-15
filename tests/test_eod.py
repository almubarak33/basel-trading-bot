"""Nothing may carry overnight: bracket legs are day orders and expire at the bell."""
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from app import engine, soft_stops, trade_manager
from app.session import NY, minutes_until, minutes_until_close

UTC_NOW = datetime(2024, 3, 4, 18, 0, tzinfo=timezone.utc)


# ---- clock helpers ------------------------------------------------------

def test_minutes_until_reads_an_iso_timestamp():
    later = UTC_NOW + timedelta(minutes=45)
    assert minutes_until(later.isoformat(), now=UTC_NOW) == pytest.approx(45)


def test_minutes_until_handles_a_zulu_suffix():
    assert minutes_until("2024-03-04T18:30:00Z", now=UTC_NOW) == pytest.approx(30)


def test_minutes_until_goes_negative_once_passed():
    assert minutes_until("2024-03-04T17:30:00Z", now=UTC_NOW) == pytest.approx(-30)


@pytest.mark.parametrize("value", [None, "", "not-a-time", 12345])
def test_minutes_until_returns_none_for_junk(value):
    assert minutes_until(value, now=UTC_NOW) is None


def test_minutes_until_close_tracks_the_standard_session():
    assert minutes_until_close(datetime(2024, 3, 4, 15, 50, tzinfo=NY)) == pytest.approx(10)
    assert minutes_until_close(datetime(2024, 3, 4, 12, 0, tzinfo=NY)) == pytest.approx(240)


def test_an_early_close_is_only_visible_through_the_broker_clock():
    """A half-day shuts at 13:00; a hardcoded 16:00 would never trigger the flatten."""
    one_pm = datetime(2024, 11, 29, 13, 0, tzinfo=NY)
    twelve_fifty = datetime(2024, 11, 29, 12, 50, tzinfo=NY)
    assert minutes_until(one_pm.isoformat(), now=twelve_fifty) == pytest.approx(10)
    assert minutes_until_close(twelve_fifty) == pytest.approx(190)   # wall clock is blind to it


# ---- manager flatten ----------------------------------------------------

class FakeAlpaca:
    def __init__(self, minutes_to_close=120, is_open=True, positions=None):
        self.minutes_to_close, self.is_open = minutes_to_close, is_open
        self._positions = positions if positions is not None else [
            {"symbol": "AAAA", "avg_entry_price": "10.00", "current_price": "10.05"}]
        self.flattened = 0
        self.closed = []

    def configured(self): return True
    async def clock(self):
        close = datetime.now(timezone.utc) + timedelta(minutes=self.minutes_to_close)
        return {"is_open": self.is_open, "next_close": close.isoformat()}
    async def risk_status(self): return {"blocked": False}
    async def positions(self): return self._positions
    async def open_orders(self): return []
    async def intraday_bars(self, symbols, minutes=180):
        return {s: [{"o": 10, "h": 10, "l": 10, "c": 10, "v": 100} for _ in range(30)] for s in symbols}
    async def market_regime(self): return {"longs_allowed": True}
    async def close_position(self, symbol): self.closed.append(symbol); return {"ok": True}
    async def close_all_positions(self): self.flattened += 1; return {"ok": True}


@pytest.fixture
def manager(monkeypatch):
    trade_manager.TRACKED.clear()
    soft_stops.clear()
    trade_manager.UNPROTECTED_CHECKS.clear()
    monkeypatch.setattr(trade_manager, "settings", dataclasses.replace(
        trade_manager.settings, paper=True, enable_orders=True, auto_manage_positions=True,
        eod_flatten_enabled=True, eod_flatten_minutes=10, trade_after_hours=False))
    monkeypatch.setattr(trade_manager, "log_event", lambda *a, **k: None)
    return trade_manager


async def run(manager, monkeypatch, broker):
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once()
    return broker


@pytest.mark.asyncio
async def test_positions_are_flattened_inside_the_window(manager, monkeypatch):
    broker = await run(manager, monkeypatch, FakeAlpaca(minutes_to_close=5))
    assert broker.flattened == 1
    assert manager.TRACKED == {}


@pytest.mark.asyncio
async def test_positions_are_left_alone_earlier_in_the_session(manager, monkeypatch):
    broker = await run(manager, monkeypatch, FakeAlpaca(minutes_to_close=120))
    assert broker.flattened == 0


@pytest.mark.asyncio
async def test_the_flatten_can_be_disabled(manager, monkeypatch):
    monkeypatch.setattr(manager, "settings",
                        dataclasses.replace(manager.settings, eod_flatten_enabled=False))
    broker = await run(manager, monkeypatch, FakeAlpaca(minutes_to_close=5))
    assert broker.flattened == 0


@pytest.mark.asyncio
async def test_nothing_is_submitted_once_the_market_is_closed(manager, monkeypatch):
    """After the bell an order would only queue for the next session."""
    broker = await run(manager, monkeypatch, FakeAlpaca(minutes_to_close=-5, is_open=False))
    assert broker.flattened == 0 and broker.closed == []


@pytest.mark.asyncio
async def test_no_flatten_when_there_is_nothing_to_close(manager, monkeypatch):
    broker = await run(manager, monkeypatch, FakeAlpaca(minutes_to_close=5, positions=[]))
    assert broker.flattened == 0


@pytest.mark.asyncio
async def test_an_unreadable_close_time_does_not_trigger_a_flatten(manager, monkeypatch):
    broker = FakeAlpaca(minutes_to_close=5)
    async def broken_clock(): return {"is_open": True, "next_close": "garbage"}
    broker.clock = broken_clock
    await run(manager, monkeypatch, broker)
    assert broker.flattened == 0


# ---- entry cutoff -------------------------------------------------------

def clock_with(minutes_to_close):
    close = datetime.now(timezone.utc) + timedelta(minutes=minutes_to_close)
    return {"is_open": True, "next_close": close.isoformat()}


@pytest.fixture
def entry_settings(monkeypatch):
    monkeypatch.setattr(engine, "settings", dataclasses.replace(
        engine.settings, no_entry_minutes_before_close=30, trade_after_hours=False))


def test_entries_are_blocked_near_the_close(entry_settings):
    assert engine._entry_window_closed(clock_with(15)) is True


def test_entries_are_allowed_earlier(entry_settings):
    assert engine._entry_window_closed(clock_with(90)) is False


def test_the_cutoff_sits_before_the_flatten(entry_settings):
    """Otherwise the bot would open trades the flatten immediately closes."""
    assert engine.settings.no_entry_minutes_before_close >= trade_manager.settings.eod_flatten_minutes


def test_an_unreadable_close_time_does_not_block_entries(entry_settings):
    assert engine._entry_window_closed({"next_close": None}) is False
