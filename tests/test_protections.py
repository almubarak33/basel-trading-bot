"""Circuit breakers: stop trading when the recent record says to.

The daily equity limit never fired once across 44 backtested sessions while one
exit bucket lost $3,514 in −0.47 R instalments. These guards read the trade
record instead of the day's equity, so a slow bleed is visible to them.
"""
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.protections import (GLOBAL, ClosedTrade, ProtectionTracker, blocking_lock,
                             drawdown_lock, evaluate, from_ledger, losing_streak_lock,
                             weak_symbol_locks)

NOW = datetime(2024, 3, 4, 15, 0, tzinfo=timezone.utc)


def cfg(**kw):
    base = dict(protections_enabled=True, guard_loss_trades=4, guard_loss_lookback_minutes=120,
                guard_loss_lock_minutes=90, guard_drawdown_pct=0.02,
                guard_drawdown_lookback_minutes=390, guard_drawdown_min_trades=5,
                guard_drawdown_lock_minutes=180, guard_symbol_trades=3,
                guard_symbol_lookback_minutes=1440, guard_symbol_lock_minutes=240)
    base.update(kw)
    return dataclasses.replace(settings, **base)


def trade(minutes_ago=10, pnl=-50.0, symbol="AAAA", r=-1.0, reason="stop_loss"):
    return ClosedTrade(symbol=symbol, closed_at=NOW - timedelta(minutes=minutes_ago),
                       pnl=pnl, r_multiple=r, reason=reason)


# ---- losing streak ------------------------------------------------------

def test_a_run_of_losses_halts_trading():
    losses = [trade(minutes_ago=i * 10, symbol=f"SYM{i}") for i in range(4)]
    lock = losing_streak_lock(losses, NOW, cfg())
    assert lock is not None and lock.scope == GLOBAL
    assert lock.code == "guard_losing_streak"
    assert lock.detail["losses"] == 4


def test_three_losses_are_not_yet_a_streak():
    assert losing_streak_lock([trade(minutes_ago=i * 10) for i in range(3)], NOW, cfg()) is None


def test_losses_outside_the_window_do_not_count():
    old = [trade(minutes_ago=200 + i) for i in range(6)]
    assert losing_streak_lock(old, NOW, cfg()) is None


def test_winners_do_not_count_towards_the_streak():
    mixed = [trade(pnl=+100.0, minutes_ago=i * 10) for i in range(6)]
    assert losing_streak_lock(mixed, NOW, cfg()) is None


def test_every_losing_exit_counts_not_only_stops():
    """The losses that motivated this were regime and thesis exits, not stops."""
    losses = [trade(minutes_ago=i * 10, reason="market_regime_risk_off") for i in range(4)]
    assert losing_streak_lock(losses, NOW, cfg()) is not None


def test_the_lock_runs_for_the_configured_period():
    lock = losing_streak_lock([trade(minutes_ago=i) for i in range(4)], NOW, cfg(guard_loss_lock_minutes=45))
    assert lock.until == NOW + timedelta(minutes=45)


# ---- drawdown -----------------------------------------------------------

def test_a_slow_bleed_trips_the_drawdown_guard():
    """No single trade is large; together they exceed 2% of equity."""
    bleed = [trade(minutes_ago=300 - i * 10, pnl=-90.0) for i in range(5)]
    lock = drawdown_lock(bleed, NOW, equity=20_000, cfg=cfg())
    assert lock is not None and lock.code == "guard_drawdown"
    assert lock.detail["drawdown_pct"] == pytest.approx(2.25)


def test_the_drawdown_is_measured_from_the_windows_peak():
    """A run-up then a give-back is a drawdown even while total P&L is positive."""
    rows = [trade(minutes_ago=300, pnl=+1000.0)] + [trade(minutes_ago=200 - i * 10, pnl=-120.0)
                                                     for i in range(5)]
    lock = drawdown_lock(rows, NOW, equity=20_000, cfg=cfg())
    assert lock is not None
    assert lock.detail["drawdown_pct"] == pytest.approx(3.0)


def test_a_shallow_drawdown_is_left_alone():
    rows = [trade(minutes_ago=100 - i * 10, pnl=-20.0) for i in range(5)]
    assert drawdown_lock(rows, NOW, equity=20_000, cfg=cfg()) is None


def test_the_drawdown_guard_waits_for_a_meaningful_sample():
    rows = [trade(minutes_ago=10, pnl=-900.0)]
    assert drawdown_lock(rows, NOW, equity=20_000, cfg=cfg()) is None


def test_an_unknown_equity_cannot_produce_a_percentage():
    rows = [trade(minutes_ago=100 - i * 10, pnl=-900.0) for i in range(5)]
    assert drawdown_lock(rows, NOW, equity=0, cfg=cfg()) is None


# ---- weak symbols -------------------------------------------------------

def test_a_repeatedly_failing_symbol_is_benched_alone():
    rows = [trade(symbol="BBBB", minutes_ago=i * 30) for i in range(3)]
    locks = weak_symbol_locks(rows, NOW, cfg())
    assert [l.scope for l in locks] == ["BBBB"]
    assert locks[0].code == "guard_weak_symbol"


def test_a_symbol_that_is_net_positive_keeps_trading():
    rows = [trade(symbol="BBBB", minutes_ago=10, pnl=-50.0),
            trade(symbol="BBBB", minutes_ago=20, pnl=-50.0),
            trade(symbol="BBBB", minutes_ago=30, pnl=+300.0)]
    assert weak_symbol_locks(rows, NOW, cfg()) == []


def test_one_bad_symbol_does_not_bench_the_others():
    rows = [trade(symbol="BBBB", minutes_ago=i * 10) for i in range(3)]
    rows += [trade(symbol="CCCC", minutes_ago=5, pnl=+80.0)]
    locks = weak_symbol_locks(rows, NOW, cfg())
    assert blocking_lock(locks, "BBBB", NOW) is not None
    assert blocking_lock(locks, "CCCC", NOW) is None


# ---- scope and expiry ---------------------------------------------------

def test_a_global_lock_covers_every_symbol():
    lock = losing_streak_lock([trade(minutes_ago=i, symbol=f"SYM{i}") for i in range(4)], NOW, cfg())
    assert blocking_lock([lock], "ANY", NOW) is not None
    assert blocking_lock([lock], None, NOW) is not None


def test_an_expired_lock_stops_blocking():
    lock = losing_streak_lock([trade(minutes_ago=i) for i in range(4)], NOW, cfg(guard_loss_lock_minutes=30))
    assert blocking_lock([lock], "ANY", NOW + timedelta(minutes=31)) is None


def test_guards_can_be_switched_off_entirely():
    losses = [trade(minutes_ago=i * 10) for i in range(8)]
    assert evaluate(losses, NOW, 20_000, cfg(protections_enabled=False)) == []


def test_a_clean_record_produces_no_locks():
    assert evaluate([trade(pnl=+100.0, minutes_ago=5)], NOW, 20_000, cfg()) == []


# ---- the tracker --------------------------------------------------------

def test_a_lock_survives_its_trigger_ageing_out_of_the_window():
    """Otherwise the cooling-off period ends the moment it is needed most."""
    tracker = ProtectionTracker()
    losses = [trade(minutes_ago=i, symbol=f"SYM{i}") for i in range(4)]
    tracker.update(losses, NOW, 20_000, cfg())
    assert tracker.blocked("AAAA", NOW) is not None
    later = NOW + timedelta(minutes=60)          # trades now outside the 120m window
    tracker.update(losses, later, 20_000, cfg())
    assert tracker.blocked("AAAA", later) is not None


def test_the_stand_down_is_not_extended_by_repeat_triggers():
    tracker = ProtectionTracker()
    # Distinct symbols, so only the global streak guard is in play here.
    losses = [trade(minutes_ago=i, symbol=f"SYM{i}") for i in range(4)]
    tracker.update(losses, NOW, 20_000, cfg())
    first_until = tracker.locks[0].until
    tracker.update(losses, NOW + timedelta(minutes=5), 20_000, cfg())
    assert len(tracker.locks) == 1 and tracker.locks[0].until == first_until


def test_the_tracker_releases_the_lock_when_it_expires():
    tracker = ProtectionTracker()
    tracker.update([trade(minutes_ago=i, symbol=f"SYM{i}") for i in range(4)], NOW, 20_000,
                   cfg(guard_loss_lock_minutes=30))
    after = NOW + timedelta(minutes=31)
    tracker.update([], after, 20_000, cfg())
    assert tracker.blocked("AAAA", after) is None and tracker.snapshot(after) == []


def test_the_snapshot_is_json_safe_for_the_dashboard():
    tracker = ProtectionTracker()
    tracker.update([trade(minutes_ago=i, symbol=f"SYM{i}") for i in range(4)], NOW, 20_000, cfg())
    row = tracker.snapshot(NOW)[0]
    assert set(row) == {"scope", "until", "code", "detail"}
    assert isinstance(row["until"], str)


# ---- reading the live ledger -------------------------------------------

def test_the_broker_ledger_is_converted():
    rows = [{"symbol": "aaaa", "pnl": -26.1, "reason": "stop", "closed_at": "2024-03-04T14:00:00+00:00"}]
    out = from_ledger(rows)
    assert out[0].symbol == "AAAA" and out[0].pnl == -26.1


def test_a_naive_timestamp_is_read_as_utc():
    out = from_ledger([{"symbol": "AAAA", "pnl": -1, "closed_at": "2024-03-04T14:00:00"}])
    assert out[0].closed_at.tzinfo is not None


@pytest.mark.parametrize("row", [
    {"symbol": "AAAA", "pnl": -1},                               # no close time
    {"symbol": "AAAA", "pnl": -1, "closed_at": "not-a-time"},
    {"symbol": "AAAA", "pnl": "abc", "closed_at": "2024-03-04T14:00:00Z"},
])
def test_unusable_rows_are_dropped_rather_than_guessed_at(row):
    assert from_ledger([row]) == []


def test_an_empty_ledger_is_fine():
    assert from_ledger(None) == [] and from_ledger([]) == []
