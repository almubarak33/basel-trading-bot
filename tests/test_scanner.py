"""The most-actives half of the screener must reach the strategy, not be pre-rejected."""
import dataclasses

import pytest

from app import scanner
from app.scanner import change_pct_from_snapshot

MOVERS = {"gainers": [{"symbol": "GAIN", "percent_change": 12.5}]}
ACTIVES = {"most_actives": [{"symbol": "GAIN", "volume": 9e6}, {"symbol": "BUSY", "volume": 8e6}]}


def snapshot(price=11.0, prev_close=10.0, minute_close=None, daily_close=None):
    snap = {"latestQuote": {"bp": price - 0.01, "ap": price + 0.01}}
    if price:
        snap["latestTrade"] = {"p": price}
    if prev_close:
        snap["prevDailyBar"] = {"c": prev_close}
    if minute_close:
        snap["minuteBar"] = {"c": minute_close}
    if daily_close:
        snap["dailyBar"] = {"c": daily_close}
    return snap


# ---- deriving the change -------------------------------------------------

def test_change_is_measured_against_the_previous_close():
    assert change_pct_from_snapshot(snapshot(11.0, 10.0)) == pytest.approx(10.0)


def test_a_falling_symbol_reports_a_negative_change():
    assert change_pct_from_snapshot(snapshot(9.0, 10.0)) == pytest.approx(-10.0)


def test_falls_back_through_minute_then_daily_bar_for_price():
    no_trade = {"prevDailyBar": {"c": 10.0}, "minuteBar": {"c": 10.5}}
    assert change_pct_from_snapshot(no_trade) == pytest.approx(5.0)
    daily_only = {"prevDailyBar": {"c": 10.0}, "dailyBar": {"c": 10.8}}
    assert change_pct_from_snapshot(daily_only) == pytest.approx(8.0)


@pytest.mark.parametrize("snap", [
    None, {}, {"prevDailyBar": {"c": 0}}, {"prevDailyBar": {"c": "x"}},
    {"latestTrade": {"p": 11.0}},                       # no previous close
    {"prevDailyBar": {"c": 10.0}, "latestTrade": {"p": 0}},
])
def test_unusable_snapshots_yield_zero_rather_than_raising(snap):
    assert change_pct_from_snapshot(snap) == 0.0


# ---- the scan pipeline ---------------------------------------------------

class FakeAlpaca:
    def __init__(self, snapshots):
        self.snaps = snapshots

    async def market_regime(self): return {"longs_allowed": True}
    async def movers(self, top): return MOVERS
    async def most_actives(self, top): return ACTIVES
    async def snapshots(self, symbols): return {"snapshots": {s: self.snaps.get(s, {}) for s in symbols}}
    async def intraday_bars(self, symbols, minutes=300):
        return {s: [{"o": 10, "h": 10.1, "l": 9.9, "c": 10, "v": 5000} for _ in range(40)] for s in symbols}
    async def daily_bars(self, symbols, days=20):
        return {s: [{"c": 10, "v": 1_000_000} for _ in range(20)] for s in symbols}


@pytest.fixture
def patched(monkeypatch):
    def _apply(snapshots):
        monkeypatch.setattr(scanner, "alpaca", FakeAlpaca(snapshots))
        return scanner
    return _apply


@pytest.mark.asyncio
async def test_an_actives_only_symbol_gets_its_real_change(patched):
    module = patched({"GAIN": snapshot(11.25, 10.0), "BUSY": snapshot(10.6, 10.0)})
    rows = {r["symbol"]: r for r in await module.scan()}
    assert rows["BUSY"]["change_pct"] == pytest.approx(6.0)


@pytest.mark.asyncio
async def test_the_gainers_screener_value_is_still_authoritative(patched):
    """It is what the gainers ranking was built from, so it is not recomputed."""
    module = patched({"GAIN": snapshot(11.25, 10.0), "BUSY": snapshot(10.6, 10.0)})
    rows = {r["symbol"]: r for r in await module.scan()}
    assert rows["GAIN"]["change_pct"] == pytest.approx(12.5)


@pytest.mark.asyncio
async def test_an_actives_symbol_is_no_longer_rejected_for_a_zero_move(patched):
    """The regression this fixes: every most-actives name failed MIN_CHANGE_PCT."""
    module = patched({"GAIN": snapshot(11.25, 10.0), "BUSY": snapshot(10.6, 10.0)})
    rows = {r["symbol"]: r for r in await module.scan()}
    assert "move_out_of_range" not in [c["code"] for c in rows["BUSY"]["reject_codes"]]


@pytest.mark.asyncio
async def test_a_genuinely_flat_actives_symbol_is_still_rejected(patched):
    module = patched({"GAIN": snapshot(11.25, 10.0), "BUSY": snapshot(10.0, 10.0)})
    rows = {r["symbol"]: r for r in await module.scan()}
    assert "move_out_of_range" in [c["code"] for c in rows["BUSY"]["reject_codes"]]


@pytest.mark.asyncio
async def test_a_missing_snapshot_degrades_to_zero_not_an_error(patched):
    module = patched({"GAIN": snapshot(11.25, 10.0)})
    rows = {r["symbol"]: r for r in await module.scan()}
    assert rows["BUSY"]["change_pct"] == 0.0


@pytest.mark.asyncio
async def test_both_screener_halves_reach_the_strategy(patched):
    module = patched({"GAIN": snapshot(11.25, 10.0), "BUSY": snapshot(10.6, 10.0)})
    symbols = {r["symbol"] for r in await module.scan()}
    assert symbols == {"GAIN", "BUSY"}
