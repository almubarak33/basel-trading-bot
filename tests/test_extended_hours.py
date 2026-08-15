"""Trading after the bell.

The broker's extended session accepts only plain limit orders — no bracket, no
OTO, no market order, no `DELETE /v2/positions`. Everything here exists because
of that one restriction: the entry carries no stop, so the bot has to hold the
stop itself and price every exit.
"""
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from app import engine, soft_stops, trade_manager
from app.orders import build_extended_hours_entry, build_extended_hours_exit
from app.session import (NY, in_after_hours, in_pre_market, in_regular_session,
                         minutes_until_day_end, session_end, tradeable_now)

REGULAR = datetime(2024, 3, 4, 11, 0, tzinfo=NY)
AFTER = datetime(2024, 3, 4, 17, 30, tzinfo=NY)
PRE = datetime(2024, 3, 4, 7, 0, tzinfo=NY)
NIGHT = datetime(2024, 3, 4, 22, 0, tzinfo=NY)


# ---- session windows ----------------------------------------------------

@pytest.mark.parametrize("moment,regular,after,pre", [
    (REGULAR, True, False, False),
    (AFTER, False, True, False),
    (PRE, False, False, True),
    (NIGHT, False, False, False),
    (datetime(2024, 3, 4, 16, 0, tzinfo=NY), False, True, False),   # the bell itself
    (datetime(2024, 3, 4, 20, 0, tzinfo=NY), False, False, False),  # extended close
])
def test_the_day_is_split_into_three_windows(moment, regular, after, pre):
    assert in_regular_session(moment) is regular
    assert in_after_hours(moment) is after
    assert in_pre_market(moment) is pre


def test_an_open_market_always_wins_whatever_the_wall_clock_says():
    """Holidays and half-days are the broker's calendar, not ours."""
    assert tradeable_now(NIGHT, market_open=True, after_hours=False, pre_market=False) is True


def test_after_hours_is_traded_only_when_enabled():
    assert tradeable_now(AFTER, False, after_hours=True, pre_market=False) is True
    assert tradeable_now(AFTER, False, after_hours=False, pre_market=False) is False


def test_pre_market_stays_off_while_after_hours_is_on():
    """What the user asked for: trade after the close, never before the open."""
    assert tradeable_now(PRE, False, after_hours=True, pre_market=False) is False
    assert tradeable_now(PRE, False, after_hours=True, pre_market=True) is True


def test_nothing_trades_overnight():
    assert tradeable_now(NIGHT, False, after_hours=True, pre_market=True) is False


# ---- when the trading day ends ------------------------------------------

def bell(hour=16, minute=0):
    return datetime(2024, 3, 4, hour, minute, tzinfo=NY).isoformat()


def test_the_day_ends_at_the_bell_without_extended_trading():
    assert minutes_until_day_end(bell(), after_hours=False, now=REGULAR) == pytest.approx(300)


def test_extended_trading_pushes_the_day_four_hours_out():
    assert minutes_until_day_end(bell(), after_hours=True, now=REGULAR) == pytest.approx(540)


def test_a_half_day_keeps_its_early_extended_close():
    """A 13:00 bell ends the extended session at 17:00, not 20:00."""
    noon = datetime(2024, 11, 29, 12, 0, tzinfo=NY)
    early = datetime(2024, 11, 29, 13, 0, tzinfo=NY).isoformat()
    assert minutes_until_day_end(early, after_hours=True, now=noon) == pytest.approx(300)


def test_after_the_bell_the_brokers_next_close_is_ignored():
    """It already points at tomorrow; only tonight's extended close matters."""
    tomorrow = datetime(2024, 3, 5, 16, 0, tzinfo=NY).isoformat()
    assert minutes_until_day_end(tomorrow, after_hours=True, now=AFTER) == pytest.approx(150)


def test_an_unreadable_close_time_still_yields_nothing():
    assert minutes_until_day_end("garbage", after_hours=True, now=REGULAR) is None


def test_session_end_follows_the_setting():
    assert session_end(REGULAR, after_hours=True).hour == 20
    assert session_end(REGULAR, after_hours=False).hour == 16


# ---- order shapes -------------------------------------------------------

def test_the_extended_entry_is_a_plain_limit_order():
    order = build_extended_hours_entry("aapl", 10, 187.4321, source="intel")
    assert order["symbol"] == "AAPL"
    assert order["type"] == "limit" and order["side"] == "buy"
    assert order["extended_hours"] is True
    assert order["limit_price"] == "187.43"
    assert order["time_in_force"] in {"day", "gtc"}


def test_the_extended_entry_carries_no_attached_legs():
    """The broker rejects bracket/OTO outside the regular session."""
    order = build_extended_hours_entry("AAPL", 10, 187.0, source="intel")
    assert "order_class" not in order
    assert "stop_loss" not in order and "take_profit" not in order


def test_the_extended_exit_crosses_the_spread():
    order = build_extended_hours_exit("AAPL", 10, 100.0)
    assert order["side"] == "sell" and order["type"] == "limit"
    assert order["extended_hours"] is True
    assert float(order["limit_price"]) == pytest.approx(99.5)


def test_a_sub_dollar_exit_keeps_four_decimals():
    """Sub-dollar orders are quoted to 0.0001, so 0.5% off $0.30 must not round away."""
    assert build_extended_hours_exit("AAAA", 1, 0.30)["limit_price"] == "0.2985"


def test_extended_orders_get_unique_ids():
    a = build_extended_hours_entry("AAPL", 1, 10.0, source="intel")
    b = build_extended_hours_entry("AAPL", 1, 10.0, source="intel")
    assert a["client_order_id"] != b["client_order_id"]


# ---- the software stop --------------------------------------------------

class FakeAlpaca:
    def __init__(self, is_open=True, positions=None, orders=None, minutes_to_close=120):
        self.is_open = is_open
        self._positions = positions if positions is not None else [
            {"symbol": "AAAA", "qty": "100", "avg_entry_price": "10.00", "current_price": "10.05"}]
        self.orders = orders or []
        self.minutes_to_close = minutes_to_close
        self.submitted, self.closed, self.flattened = [], [], 0

    def configured(self): return True
    async def clock(self):
        close = datetime.now(timezone.utc) + timedelta(minutes=self.minutes_to_close)
        return {"is_open": self.is_open, "next_close": close.isoformat()}
    async def risk_status(self): return {"blocked": False}
    async def positions(self): return self._positions
    async def position(self, symbol): return self._positions[0]
    async def open_orders(self): return self.orders
    async def intraday_bars(self, symbols, minutes=180):
        return {s: [{"o": 10, "h": 10, "l": 10, "c": 10, "v": 100} for _ in range(30)] for s in symbols}
    async def market_regime(self): return {"longs_allowed": True}
    async def close_position(self, symbol): self.closed.append(symbol); return {"ok": True}
    async def close_all_positions(self): self.flattened += 1; return {"ok": True}
    async def submit_order(self, payload): self.submitted.append(payload); return {"id": "x", **payload}


@pytest.fixture
def manager(monkeypatch):
    trade_manager.TRACKED.clear()
    trade_manager.UNPROTECTED_CHECKS.clear()
    soft_stops.clear()
    monkeypatch.setattr(trade_manager, "settings", dataclasses.replace(
        trade_manager.settings, paper=True, enable_orders=True, auto_manage_positions=True,
        trade_after_hours=True, trade_pre_market=False,
        eod_flatten_enabled=True, eod_flatten_minutes=10))
    monkeypatch.setattr(trade_manager, "log_event", lambda *a, **k: None)
    return trade_manager


def position(current="10.05", entry="10.00", qty="100"):
    return [{"symbol": "AAAA", "qty": qty, "avg_entry_price": entry, "current_price": current}]


@pytest.mark.asyncio
async def test_positions_are_still_managed_after_the_bell(manager, monkeypatch):
    broker = FakeAlpaca(is_open=False)
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once(now=AFTER)
    assert "AAAA" in manager.TRACKED


@pytest.mark.asyncio
async def test_the_bot_still_sleeps_overnight(manager, monkeypatch):
    broker = FakeAlpaca(is_open=False)
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once(now=NIGHT)
    assert manager.TRACKED == {} and broker.submitted == []


@pytest.mark.asyncio
async def test_a_broker_stop_is_remembered_for_after_the_bell(manager, monkeypatch):
    """The stop leg is a day order; it dies at 16:00 while the position lives on."""
    broker = FakeAlpaca(orders=[{"symbol": "AAAA", "side": "sell", "type": "stop", "stop_price": "9.60"}])
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once(now=REGULAR)
    assert soft_stops.get("AAAA") == pytest.approx(9.60)


@pytest.mark.asyncio
async def test_the_software_stop_closes_a_position_the_broker_no_longer_guards(manager, monkeypatch):
    broker = FakeAlpaca(is_open=False, positions=position(current="9.40"))
    monkeypatch.setattr(manager, "alpaca", broker)
    soft_stops.remember("AAAA", 9.60)
    await manager.manage_once(now=AFTER)
    assert len(broker.submitted) == 1
    order = broker.submitted[0]
    assert order["side"] == "sell" and order["extended_hours"] is True
    assert order["qty"] == "100"
    assert soft_stops.get("AAAA") == 0.0


@pytest.mark.asyncio
async def test_the_software_stop_holds_above_the_line(manager, monkeypatch):
    broker = FakeAlpaca(is_open=False, positions=position(current="9.80"))
    monkeypatch.setattr(manager, "alpaca", broker)
    soft_stops.remember("AAAA", 9.60)
    await manager.manage_once(now=AFTER)
    assert broker.submitted == []
    assert manager.UNPROTECTED_CHECKS == {}


@pytest.mark.asyncio
async def test_a_working_broker_stop_is_left_to_the_broker(manager, monkeypatch):
    """Duplicating it in software would sell a position the stop leg already has."""
    broker = FakeAlpaca(positions=position(current="9.40"),
                        orders=[{"symbol": "AAAA", "side": "sell", "type": "stop", "stop_price": "9.60"}])
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once(now=REGULAR)
    assert broker.submitted == [] and broker.closed == []


@pytest.mark.asyncio
async def test_the_software_stop_anchors_r_when_no_stop_order_exists(manager, monkeypatch):
    broker = FakeAlpaca(is_open=False)
    monkeypatch.setattr(manager, "alpaca", broker)
    soft_stops.remember("AAAA", 9.60)
    await manager.manage_once(now=AFTER)
    assert manager.TRACKED["AAAA"].risk_per_share() == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_stops_are_dropped_once_the_position_is_gone(manager, monkeypatch):
    monkeypatch.setattr(manager, "alpaca", FakeAlpaca(is_open=False, positions=[]))
    soft_stops.remember("AAAA", 9.60)
    await manager.manage_once(now=AFTER)
    assert soft_stops.snapshot() == {}


# ---- day-end flatten in the extended session ----------------------------

@pytest.mark.asyncio
async def test_the_flatten_waits_for_the_extended_close(manager, monkeypatch):
    """15:50 is no longer the end of the day when after-hours trading is on."""
    broker = FakeAlpaca(minutes_to_close=5)
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once(now=REGULAR)
    assert broker.flattened == 0 and broker.submitted == []


@pytest.mark.asyncio
async def test_the_flatten_fires_before_the_extended_close(manager, monkeypatch):
    broker = FakeAlpaca(is_open=False)
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once(now=datetime(2024, 3, 4, 19, 55, tzinfo=NY))
    assert len(broker.submitted) == 1
    assert broker.submitted[0]["side"] == "sell"
    assert broker.flattened == 0     # a market close would be rejected at 19:55
    assert manager.TRACKED == {}


@pytest.mark.asyncio
async def test_one_failed_exit_does_not_abandon_the_rest(manager, monkeypatch):
    broker = FakeAlpaca(is_open=False, positions=[
        {"symbol": "AAAA", "qty": "0", "avg_entry_price": "10", "current_price": "10"},
        {"symbol": "BBBB", "qty": "50", "avg_entry_price": "10", "current_price": "10"}])
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once(now=datetime(2024, 3, 4, 19, 55, tzinfo=NY))
    assert [o["symbol"] for o in broker.submitted] == ["BBBB"]


# ---- the engine's entry gate --------------------------------------------

@pytest.fixture
def entry_engine(monkeypatch):
    monkeypatch.setattr(engine, "settings", dataclasses.replace(
        engine.settings, no_entry_minutes_before_close=30,
        trade_after_hours=True, trade_pre_market=False))
    return engine


def test_the_engine_works_after_the_bell(entry_engine):
    assert entry_engine._session_open({"is_open": False}, now=AFTER) is True


def test_the_engine_stays_out_of_the_pre_market(entry_engine):
    assert entry_engine._session_open({"is_open": False}, now=PRE) is False


def test_the_engine_sleeps_overnight(entry_engine):
    assert entry_engine._session_open({"is_open": False}, now=NIGHT) is False


def test_entries_run_past_the_bell_when_after_hours_is_on(entry_engine):
    """15:45 would have been inside the old cutoff; the day now ends at 20:00."""
    assert entry_engine._entry_window_closed({"next_close": bell()},
                                             now=datetime(2024, 3, 4, 15, 45, tzinfo=NY)) is False


def test_entries_stop_before_the_extended_close(entry_engine):
    tomorrow = datetime(2024, 3, 5, 16, 0, tzinfo=NY).isoformat()
    assert entry_engine._entry_window_closed({"next_close": tomorrow},
                                             now=datetime(2024, 3, 4, 19, 40, tzinfo=NY)) is True


def test_the_extended_cutoff_still_sits_before_the_flatten(entry_engine):
    assert entry_engine.settings.no_entry_minutes_before_close >= trade_manager.settings.eod_flatten_minutes


# ---- what the dashboard is told ------------------------------------------

@pytest.mark.parametrize("market_open,moment,phase", [
    (True, REGULAR, "regular"),
    (False, AFTER, "after_hours"),
    (False, PRE, "pre_market"),
    (False, NIGHT, "closed"),
    (True, NIGHT, "regular"),
])
def test_the_status_names_the_window_rather_than_just_open_or_shut(market_open, moment, phase):
    from app.main import session_phase
    assert session_phase(market_open, moment) == phase
