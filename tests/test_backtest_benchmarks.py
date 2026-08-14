from datetime import date, datetime, timezone

from app.backtest.data import BarStore
from app.backtest.config import BacktestConfig
from app.backtest.runner import _benchmark_stats, BacktestResult, EquityPoint
from app.backtest.metrics import summarize


def _bar(ts, o, c):
    return {"t": ts, "o": o, "h": max(o, c), "l": min(o, c), "c": c, "v": 1000}


def test_benchmark_stats_use_same_window_first_open_last_close():
    store = BarStore()
    store.add_minute_bars("SPY", [
        _bar("2024-04-01T13:30:00Z", 100, 101),
        _bar("2024-04-02T19:59:00Z", 109, 110),
    ])
    store.add_minute_bars("QQQ", [
        _bar("2024-04-01T13:30:00Z", 200, 202),
        _bar("2024-04-02T19:59:00Z", 218, 220),
    ])
    cfg = BacktestConfig(start=date(2024,4,1), end=date(2024,4,2), symbols=[])
    stats = _benchmark_stats(store, cfg)
    assert stats["SPY"]["total_return_pct"] == 10.0
    assert stats["QQQ"]["total_return_pct"] == 10.0


def test_summary_reports_alpha_vs_benchmarks():
    result = BacktestResult(
        trades=[],
        equity_curve=[
            EquityPoint(datetime(2024,4,1,14,0,tzinfo=timezone.utc), 20000),
            EquityPoint(datetime(2024,4,2,20,0,tzinfo=timezone.utc), 22000),
        ],
        daily_equity=[(date(2024,4,1), 20500), (date(2024,4,2), 22000)],
        starting_equity=20000,
        sessions=2,
        orders_placed=0,
        orders_cancelled=0,
        guard_days=0,
        config=BacktestConfig(start=date(2024,4,1), end=date(2024,4,2), symbols=[]),
        benchmarks={
            "SPY": {"available": True, "total_return_pct": 5.0},
            "QQQ": {"available": True, "total_return_pct": 8.0},
        },
    )
    summary = summarize(result)
    assert summary["equity"]["total_return_pct"] == 10.0
    assert summary["benchmarks"]["SPY"]["alpha_pct"] == 5.0
    assert summary["benchmarks"]["QQQ"]["alpha_pct"] == 2.0
    assert summary["benchmark_test"]["beats_all"] is True
    assert summary["benchmark_test"]["alpha_vs_best_pct"] == 2.0
