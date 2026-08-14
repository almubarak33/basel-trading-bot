"""Backtest configuration and strategy-parameter overriding."""
from __future__ import annotations
import contextlib
import dataclasses
from dataclasses import dataclass, field
from datetime import date

from .. import scanner as scanner_module
from .. import strategy as strategy_module
from ..config import Settings, settings as live_settings

# Modules that bound `settings` at import time and must be patched for a sweep.
_SETTINGS_CONSUMERS = (strategy_module, scanner_module)


@dataclass
class ExecutionModel:
    """Assumptions about how orders actually fill. Every one of these is a modelling
    choice, not a measurement — they are surfaced in the report so results are
    read with the right amount of scepticism."""

    # A limit entry is abandoned if it has not filled within this many bars.
    entry_timeout_bars: int = 5
    # Stop orders become market orders; this is the adverse fill penalty.
    stop_slippage_bps: float = 5.0
    # Minute bars carry no quotes, so the spread filter is fed an estimate:
    # spread ≈ (tick_size * spread_ticks) / price, floored at min_spread_pct.
    spread_ticks: float = 1.5
    tick_size: float = 0.01
    min_spread_pct: float = 0.04
    # When a bar's range covers both stop and target, assume the stop filled first.
    same_bar_stop_first: bool = True
    # Positions are managed starting the bar *after* the entry fill; sub-minute
    # adverse paths inside the fill bar are not modelled.
    flatten_at_close: bool = True


@dataclass
class BacktestConfig:
    start: date
    end: date
    symbols: list[str]
    starting_equity: float = 20000.0

    # Strategy knobs to override for this run (any field name from Settings).
    overrides: dict = field(default_factory=dict)

    execution: ExecutionModel = field(default_factory=ExecutionModel)

    # Live keeps auto-trading off after a daily-loss stop until a human re-enables
    # it. A multi-day backtest resumes the next session so later days still sample.
    resume_after_guard_next_day: bool = True

    # Most-actives symbols get their real day change, matching the live scanner.
    # Set True to reproduce the legacy hardcoded 0, which rejected all of them.
    legacy_screener_change: bool = False

    # Anchor R to the real entry stop, matching the live manager. Set False to
    # reproduce the legacy flat-1.5% assumption for comparison.
    use_true_initial_risk: bool = True

    def effective_settings(self) -> Settings:
        return dataclasses.replace(live_settings, **self.overrides) if self.overrides else live_settings


@contextlib.contextmanager
def override_settings(cfg_settings: Settings):
    """Temporarily rebind `settings` inside modules that imported it directly."""
    previous = [(m, m.settings) for m in _SETTINGS_CONSUMERS]
    for module, _ in previous:
        module.settings = cfg_settings
    try:
        yield cfg_settings
    finally:
        for module, original in previous:
            module.settings = original
