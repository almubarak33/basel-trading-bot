from datetime import date, datetime, timezone

from app.backtest.broker import ClosedTrade
from app.backtest.config import BacktestConfig
from app.backtest.metrics import format_report, summarize
from app.backtest.runner import BacktestResult, EquityPoint

NOW = datetime(2024, 3, 4, 15, 0, tzinfo=timezone.utc)


def trade(pnl, r, reason="take_profit", grade="A+", hour=10):
    return ClosedTrade(symbol="AAAA", entry_time=NOW, entry_price=10.0, exit_time=NOW,
                       exit_price=10.0 + pnl, qty=1, stop=9.5, target=11.0, reason=reason,
                       pnl=pnl, r_multiple=r, meta={"grade": grade, "entry_hour": hour})


def result(trades, equity_points, daily, starting=20_000.0, **kwargs):
    return BacktestResult(
        trades=trades,
        equity_curve=[EquityPoint(NOW, value) for value in equity_points],
        daily_equity=daily, starting_equity=starting, sessions=len(daily),
        orders_placed=kwargs.get("orders_placed", len(trades)),
        orders_cancelled=kwargs.get("orders_cancelled", 0),
        guard_days=kwargs.get("guard_days", 0),
        config=BacktestConfig(start=date(2024, 3, 4), end=date(2024, 3, 5), symbols=["AAAA"]),
    )


def test_win_rate_and_expectancy():
    summary = summarize(result(
        [trade(100, 2.0), trade(100, 2.0), trade(-50, -1.0), trade(-50, -1.0)],
        [20_000, 20_100], [(date(2024, 3, 4), 20_100.0)]))
    assert summary["trades"]["win_rate_pct"] == 50.0
    assert summary["trades"]["expectancy_r"] == 0.5
    assert summary["trades"]["avg_win_r"] == 2.0
    assert summary["trades"]["avg_loss_r"] == -1.0


def test_profit_factor_is_gross_win_over_gross_loss():
    summary = summarize(result([trade(300, 3.0), trade(-100, -1.0)],
                               [20_000], [(date(2024, 3, 4), 20_200.0)]))
    assert summary["trades"]["profit_factor"] == 3.0


def test_max_drawdown_is_measured_peak_to_trough():
    summary = summarize(result([], [20_000, 22_000, 19_800, 21_000],
                               [(date(2024, 3, 4), 21_000.0)]))
    assert summary["equity"]["max_drawdown_pct"] == 10.0


def test_total_return_uses_the_final_daily_equity():
    summary = summarize(result([], [20_000], [(date(2024, 3, 4), 22_000.0)]))
    assert summary["equity"]["total_return_pct"] == 10.0


def test_empty_backtest_does_not_divide_by_zero():
    summary = summarize(result([], [], []))
    assert summary["trades"]["count"] == 0
    assert summary["trades"]["win_rate_pct"] == 0.0
    assert summary["equity"]["max_drawdown_pct"] == 0.0


def test_fill_rate_reflects_unfilled_orders():
    summary = summarize(result([trade(100, 2.0)], [20_000], [(date(2024, 3, 4), 20_100.0)],
                               orders_placed=4, orders_cancelled=3))
    assert summary["trades"]["fill_rate_pct"] == 25.0
    assert summary["trades"]["orders_never_filled"] == 3


def test_breakdowns_group_by_reason_grade_and_hour():
    summary = summarize(result(
        [trade(100, 2.0, "take_profit", "A+", 10), trade(-50, -1.0, "stop_loss", "B", 14)],
        [20_000], [(date(2024, 3, 4), 20_050.0)]))
    assert summary["by_exit_reason"]["take_profit"]["trades"] == 1
    assert summary["by_grade"]["B"]["win_rate_pct"] == 0.0
    assert summary["by_entry_hour"]["14:00 ET"]["trades"] == 1


def test_guard_rate_is_reported():
    summary = summarize(result([], [20_000],
                               [(date(2024, 3, 4), 19_000.0), (date(2024, 3, 5), 19_000.0)],
                               guard_days=1))
    assert summary["risk"]["guard_rate_pct"] == 50.0


def test_report_renders_without_error_on_an_empty_run():
    text = format_report(summarize(result([], [], [])), ["assumption"])
    assert "BACKTEST REPORT" in text and "assumption" in text


def test_set_values_coerce_to_the_right_type():
    """--set x=false must not become the truthy string "false"."""
    from app.backtest.cli import _coerce
    assert _coerce("false") is False and _coerce("off") is False
    assert _coerce("true") is True and _coerce("yes") is True
    assert _coerce("85") == 85.0
    assert _coerce("2.5") == 2.5
    assert _coerce("PULLBACK") == "PULLBACK"
