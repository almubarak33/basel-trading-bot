"""The manager must anchor R to the real entry stop, not a flat assumption."""
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from app import trade_manager
from app.alpaca import extract_stop_prices
from app.exits import PositionState


def stop_order(symbol="AAAA", price="9.50", side="sell", type_="stop"):
    return {"symbol": symbol, "side": side, "type": type_, "stop_price": price}


# ---- parsing broker orders ---------------------------------------------

def test_reads_a_flat_stop_order():
    assert extract_stop_prices([stop_order()]) == {"AAAA": 9.50}


def test_reads_a_stop_nested_in_a_bracket_parent():
    parent = {"symbol": "AAAA", "side": "buy", "type": "limit",
              "legs": [stop_order(), {"symbol": "AAAA", "side": "sell", "type": "limit", "limit_price": "11"}]}
    assert extract_stop_prices([parent]) == {"AAAA": 9.50}


def test_ignores_take_profit_and_entry_orders():
    orders = [{"symbol": "AAAA", "side": "sell", "type": "limit", "limit_price": "11"},
              {"symbol": "AAAA", "side": "buy", "type": "stop", "stop_price": "12"}]
    assert extract_stop_prices(orders) == {}


@pytest.mark.parametrize("type_", ["stop", "stop_limit", "trailing_stop"])
def test_accepts_every_stop_flavour(type_):
    assert extract_stop_prices([stop_order(type_=type_)]) == {"AAAA": 9.50}


def test_the_highest_stop_wins_because_it_triggers_first():
    assert extract_stop_prices([stop_order(price="9.20"), stop_order(price="9.80")]) == {"AAAA": 9.80}


def test_handles_missing_and_malformed_payloads():
    assert extract_stop_prices([]) == {}
    assert extract_stop_prices(None) == {}
    assert extract_stop_prices([stop_order(price="")]) == {}
    assert extract_stop_prices([stop_order(price="not-a-number")]) == {}
    assert extract_stop_prices([{"side": "sell", "type": "stop", "stop_price": "9.5"}]) == {}


def test_symbols_are_normalised_to_upper_case():
    assert extract_stop_prices([stop_order(symbol="aaaa")]) == {"AAAA": 9.50}


# ---- manager wiring -----------------------------------------------------

class FakeAlpaca:
    def __init__(self, orders, positions, minutes_to_close=120):
        self.orders, self._positions = orders, positions
        self.minutes_to_close = minutes_to_close

    def configured(self): return True
    async def clock(self):
        close = datetime.now(timezone.utc) + timedelta(minutes=self.minutes_to_close)
        return {"is_open": True, "next_close": close.isoformat()}
    async def close_all_positions(self): return {"ok": True}
    async def risk_status(self): return {"blocked": False}
    async def positions(self): return self._positions
    async def open_orders(self): return self.orders
    async def intraday_bars(self, symbols, minutes=180):
        return {s: [{"o": 10, "h": 10, "l": 10, "c": 10, "v": 100} for _ in range(30)] for s in symbols}
    async def market_regime(self): return {"longs_allowed": True}
    async def close_position(self, symbol): return {"ok": True}


@pytest.fixture
def manager(monkeypatch):
    """Run manage_once against a fake broker with orders enabled."""
    trade_manager.TRACKED.clear()
    enabled = dataclasses.replace(trade_manager.settings, paper=True, enable_orders=True,
                                  auto_manage_positions=True)
    monkeypatch.setattr(trade_manager, "settings", enabled)
    monkeypatch.setattr(trade_manager, "log_event", lambda *a, **k: None)
    return trade_manager


POSITION = [{"symbol": "AAAA", "avg_entry_price": "10.00", "current_price": "10.05"}]


@pytest.mark.asyncio
async def test_manager_anchors_risk_to_the_broker_stop(manager, monkeypatch):
    monkeypatch.setattr(manager, "alpaca", FakeAlpaca([stop_order(price="9.60")], POSITION))
    await manager.manage_once()
    assert manager.TRACKED["AAAA"].risk_per_share() == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_manager_falls_back_when_no_stop_is_working(manager, monkeypatch):
    monkeypatch.setattr(manager, "alpaca", FakeAlpaca([], POSITION))
    await manager.manage_once()
    assert manager.TRACKED["AAAA"].risk_per_share() == pytest.approx(0.15)


@pytest.mark.asyncio
async def test_a_stop_discovered_later_still_gets_picked_up(manager, monkeypatch):
    """The bracket legs may not be working yet on the first management pass."""
    broker = FakeAlpaca([], POSITION)
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once()
    assert manager.TRACKED["AAAA"].initial_risk_per_share is None
    broker.orders = [stop_order(price="9.60")]
    await manager.manage_once()
    assert manager.TRACKED["AAAA"].risk_per_share() == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_a_trailing_stop_does_not_rewrite_the_original_risk(manager, monkeypatch):
    """R stays measured against the risk taken at entry, not the current stop."""
    broker = FakeAlpaca([stop_order(price="9.60")], POSITION)
    monkeypatch.setattr(manager, "alpaca", broker)
    await manager.manage_once()
    broker.orders = [stop_order(price="9.95")]
    await manager.manage_once()
    assert manager.TRACKED["AAAA"].risk_per_share() == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_a_stop_above_entry_is_rejected_as_nonsense(manager, monkeypatch):
    monkeypatch.setattr(manager, "alpaca", FakeAlpaca([stop_order(price="10.50")], POSITION))
    await manager.manage_once()
    assert manager.TRACKED["AAAA"].risk_per_share() == pytest.approx(0.15)


def test_the_fallback_is_only_used_when_no_real_risk_is_known():
    known = PositionState("AAAA", 10.0, datetime.now(timezone.utc), 10.0, initial_risk_per_share=0.4)
    unknown = PositionState("AAAA", 10.0, datetime.now(timezone.utc), 10.0)
    assert known.risk_per_share() == 0.4
    assert unknown.risk_per_share() == 0.15
