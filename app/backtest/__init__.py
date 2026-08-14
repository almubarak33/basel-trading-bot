"""Historical replay harness for the Basel trading bot.

The backtester drives the *production* strategy, intelligence, arming and exit
code over recorded market data, so a result here reflects what the live engine
would have decided — not a parallel reimplementation of it.
"""
from .config import BacktestConfig, ExecutionModel
from .data import BarStore, fetch_history
from .metrics import format_report, summarize
from .runner import BacktestResult, run_backtest

__all__ = [
    "BacktestConfig", "ExecutionModel", "BarStore", "fetch_history",
    "run_backtest", "BacktestResult", "summarize", "format_report",
]
