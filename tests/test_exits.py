from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.exits import PositionState, evaluate_exit


@dataclass
class Cfg:
    thesis_fail_checks: int = 2
    protect_profit_after_r: float = 1.0
    protected_floor_r: float = 0.15
    max_hold_minutes: int = 90
    regime_exit_enabled: bool = True


NOW = datetime(2024, 3, 4, 15, 0, tzinfo=timezone.utc)
RISK_ON = {"longs_allowed": True}
RISK_OFF = {"longs_allowed": False}


def bars(price, count=30, volume=1000):
    return [{"o": price, "h": price, "l": price, "c": price, "v": volume} for _ in range(count)]


def state(entry=10.0, high=10.0, first_seen=NOW, risk=None):
    return PositionState(symbol="AAAA", entry=entry, first_seen=first_seen, high=high,
                         initial_risk_per_share=risk)


def test_holds_without_enough_history():
    assert evaluate_exit(state(), 10.0, bars(10.0, count=5), RISK_ON, NOW, Cfg()) is None


def test_thesis_failure_needs_consecutive_checks():
    position = state()
    below = bars(11.0)  # EMA20/VWAP sit at 11, price is under both
    assert evaluate_exit(position, 9.0, below, RISK_ON, NOW, Cfg()) is None
    decision = evaluate_exit(position, 9.0, below, RISK_ON, NOW, Cfg())
    assert decision.reason == "thesis_invalidated"


def test_a_recovering_bar_resets_the_failure_streak():
    position = state()
    assert evaluate_exit(position, 9.0, bars(11.0), RISK_ON, NOW, Cfg()) is None
    assert evaluate_exit(position, 12.0, bars(11.0), RISK_ON, NOW, Cfg()) is None
    assert position.fail_checks == 0


def test_profit_protection_fires_after_giving_back_a_run():
    # Entry 10, fallback risk 1.5% = 0.15/share. High of 10.20 is +1.33R.
    position = state(high=10.20)
    decision = evaluate_exit(position, 10.01, bars(9.5), RISK_ON, NOW, Cfg())
    assert decision.reason == "profit_protection"


def test_no_profit_protection_before_the_run_happens():
    position = state(high=10.05)
    assert evaluate_exit(position, 10.01, bars(9.5), RISK_ON, NOW, Cfg()) is None


def test_risk_off_regime_closes_a_losing_position():
    position = state()
    decision = evaluate_exit(position, 9.90, bars(9.5), RISK_OFF, NOW, Cfg())
    assert decision.reason == "market_regime_risk_off"


def test_risk_off_regime_leaves_a_winner_alone():
    position = state()
    assert evaluate_exit(position, 10.50, bars(9.5), RISK_OFF, NOW, Cfg()) is None


def test_the_regime_exit_can_be_switched_off():
    """It is the largest single loss source in backtests, so it must be A/B-able."""
    position = state()
    assert evaluate_exit(position, 9.90, bars(9.5), RISK_OFF, NOW, Cfg(regime_exit_enabled=False)) is None


def test_time_stop_closes_a_stalled_position():
    position = state(first_seen=NOW - timedelta(minutes=120))
    decision = evaluate_exit(position, 10.02, bars(9.5), RISK_ON, NOW, Cfg())
    assert decision.reason == "time_stop"


def test_time_stop_spares_a_position_that_is_working():
    position = state(first_seen=NOW - timedelta(minutes=120))
    assert evaluate_exit(position, 10.30, bars(9.5), RISK_ON, NOW, Cfg()) is None


def test_fallback_risk_is_one_and_a_half_percent_of_entry():
    assert state(entry=10.0).risk_per_share() == 0.15


def test_true_risk_overrides_the_fallback():
    assert state(entry=10.0, risk=0.40).risk_per_share() == 0.40


def test_true_risk_changes_the_profit_protection_trigger():
    """With a real 0.40 stop the same run is only +0.5R, so nothing fires."""
    position = state(high=10.20, risk=0.40)
    assert evaluate_exit(position, 10.01, bars(9.5), RISK_ON, NOW, Cfg()) is None
