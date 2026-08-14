"""End-to-end replay checks against the real strategy/intelligence/exit code."""
from datetime import date, timedelta

import pytest

from app.backtest.config import BacktestConfig, ExecutionModel, override_settings
from app.backtest.metrics import summarize
from app.backtest.runner import run_backtest
from app.backtest.synthetic import build_store
from app.config import settings as live_settings
from app import strategy as strategy_module

START = date(2024, 3, 4)
DAYS = [START + timedelta(days=i) for i in range(5)]
# Loosened so the constructed synthetic setups reliably reach the order stage;
# these thresholds exercise the machinery, they are not a strategy claim.
PERMISSIVE = {"min_score": 70, "min_rvol": 1.0}


@pytest.fixture(scope="module")
def store():
    return build_store(DAYS, momentum_symbols={"AAAA": 9.0, "BBBB": 14.0},
                       quiet_symbols={"CCCC": 22.0})


def config(**kwargs):
    base = dict(start=DAYS[0], end=DAYS[-1], symbols=["AAAA", "BBBB", "CCCC"],
                starting_equity=20_000.0, overrides=dict(PERMISSIVE))
    base.update(kwargs)
    return BacktestConfig(**base)


def test_replay_produces_trades(store):
    result = run_backtest(store, config())
    assert result.sessions == len(DAYS)
    assert len(result.trades) > 0


def test_replay_is_deterministic(store):
    first = run_backtest(store, config())
    second = run_backtest(store, config())
    assert [(t.symbol, t.entry_time, t.exit_price) for t in first.trades] == \
           [(t.symbol, t.entry_time, t.exit_price) for t in second.trades]


def test_quiet_symbol_is_never_traded(store):
    result = run_backtest(store, config())
    assert all(t.symbol != "CCCC" for t in result.trades)


def test_every_trade_closes_within_its_own_session(store):
    result = run_backtest(store, config())
    for t in result.trades:
        assert t.exit_time.date() == t.entry_time.date()
        assert t.exit_time >= t.entry_time


def test_no_trade_opens_during_the_opening_delay(store):
    from app.session import NY
    result = run_backtest(store, config())
    for t in result.trades:
        local = t.entry_time.astimezone(NY)
        assert (local.hour, local.minute) >= (9, 40)


def test_open_positions_never_exceed_the_configured_cap(store):
    result = run_backtest(store, config(overrides={**PERMISSIVE, "max_open_positions": 1}))
    events = sorted([(t.entry_time, 1) for t in result.trades] +
                    [(t.exit_time, -1) for t in result.trades])
    concurrent = peak = 0
    for _, delta in events:
        concurrent += delta
        peak = max(peak, concurrent)
    assert peak <= 1


def test_position_size_respects_the_risk_budget(store):
    result = run_backtest(store, config())
    budget = 20_000 * live_settings.risk_per_trade
    for t in result.trades:
        risk_dollars = (t.entry_price - t.stop) * t.qty
        # Equity drifts during the run, so allow a little headroom over the starting budget.
        assert risk_dollars <= budget * 1.1


def test_position_size_is_capped_by_notional_exposure(store):
    """The 15%-of-equity cap binds before the risk budget on tight stops."""
    result = run_backtest(store, config())
    for t in result.trades:
        assert t.entry_price * t.qty <= 20_000 * 0.15 * 1.1


def test_every_trade_has_a_positive_reward_to_risk_target(store):
    result = run_backtest(store, config())
    for t in result.trades:
        assert t.target > t.entry_price > t.stop > 0


def test_summary_is_internally_consistent(store):
    result = run_backtest(store, config())
    summary = summarize(result)
    assert summary["trades"]["count"] == len(result.trades)
    wins = len([t for t in result.trades if t.pnl > 0])
    assert summary["trades"]["win_rate_pct"] == pytest.approx(wins/len(result.trades)*100, abs=0.1)


def test_a_hostile_regime_blocks_all_entries(store):
    """With SPY/QQQ excluded the regime gate has no data and must refuse longs."""
    result = run_backtest(store, config(symbols=["AAAA", "BBBB", "CCCC"]))
    stripped = build_store(DAYS, momentum_symbols={"AAAA": 9.0}, quiet_symbols={})
    stripped.minute.pop("SPY", None)
    stripped.minute.pop("QQQ", None)
    blocked = run_backtest(stripped, config(symbols=["AAAA"]))
    assert len(result.trades) > 0
    assert blocked.trades == []


def test_an_impossible_score_threshold_yields_no_trades(store):
    result = run_backtest(store, config(overrides={"min_score": 101}))
    assert result.trades == []
    assert result.orders_placed == 0


def test_settings_overrides_are_restored_afterwards(store):
    original = strategy_module.settings
    run_backtest(store, config())
    assert strategy_module.settings is original


def test_override_context_manager_restores_on_error():
    original = strategy_module.settings
    with pytest.raises(RuntimeError):
        with override_settings(live_settings):
            raise RuntimeError("boom")
    assert strategy_module.settings is original


def test_true_initial_risk_changes_manager_behaviour(store):
    """The live 1.5% risk assumption materially misprices R against the real stop.

    Feeding the manager the true entry risk changes which exits fire, which is the
    whole reason the assumption is worth removing.
    """
    faithful = run_backtest(store, config(use_true_initial_risk=False))
    corrected = run_backtest(store, config(use_true_initial_risk=True))
    assert sorted(t.reason for t in faithful.trades) != sorted(t.reason for t in corrected.trades)
    # The mispriced R triggers protective exits at the wrong distance from entry.
    assert sum(t.reason == "stop_loss" for t in faithful.trades) > \
           sum(t.reason == "stop_loss" for t in corrected.trades)


def test_flatten_at_close_can_be_disabled(store):
    kept = run_backtest(store, config(execution=ExecutionModel(flatten_at_close=False)))
    assert all(t.reason != "session_close" for t in kept.trades)
