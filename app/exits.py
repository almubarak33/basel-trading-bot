"""Pure exit-decision logic, shared by the live trade manager and the backtester.

The live manager owns the broker IO; everything that decides *whether* to exit
lives here so a backtest exercises the same rules the bot runs in production.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

from .indicators import ema, num, vwap

# Fallback risk-per-share used when the true entry stop is unknown (see PositionState).
FALLBACK_RISK_PCT = 0.015
MIN_BARS_FOR_MANAGEMENT = 20
REGIME_EXIT_R = -0.35
TIME_STOP_MIN_R = 0.5


@dataclass
class PositionState:
    """Mutable per-position tracking carried across management checks."""
    symbol: str
    entry: float
    first_seen: datetime
    high: float
    fail_checks: int = 0
    # Real risk-per-share from the entry stop. When None the manager falls back to a
    # flat 1.5% assumption, which is what the live bot does today because Alpaca
    # positions carry no stop metadata. Supplying it makes every R figure exact.
    initial_risk_per_share: float | None = None

    def risk_per_share(self) -> float:
        if self.initial_risk_per_share and self.initial_risk_per_share > 0:
            return self.initial_risk_per_share
        return max(self.entry * FALLBACK_RISK_PCT, 0.01)


@dataclass
class ExitDecision:
    reason: str
    meta: dict = field(default_factory=dict)


def evaluate_exit(state: PositionState, current: float, bars: list[dict], regime: dict,
                  now: datetime, cfg) -> ExitDecision | None:
    """Decide whether an open long should be closed. Mutates `state` tracking fields.

    Returns None when the position should be held (including when there is not yet
    enough intraday history to manage it).
    """
    closes = [num(b.get("c")) for b in bars if num(b.get("c")) > 0]
    if len(closes) < MIN_BARS_FOR_MANAGEMENT or state.entry <= 0 or current <= 0:
        return None

    ema20 = ema(closes[-80:], 20)
    vw = vwap(bars)
    state.high = max(state.high, current)
    held_minutes = (now - state.first_seen).total_seconds() / 60

    risk = state.risk_per_share()
    r_now = (current - state.entry) / risk
    r_high = (state.high - state.entry) / risk

    thesis_failed = current < ema20 and current < vw
    state.fail_checks = state.fail_checks + 1 if thesis_failed else 0

    if state.fail_checks >= cfg.thesis_fail_checks:
        return ExitDecision("thesis_invalidated", {"current": current, "ema20": ema20, "vwap": vw, "r_now": round(r_now,2)})

    if r_high >= cfg.protect_profit_after_r and r_now <= cfg.protected_floor_r:
        return ExitDecision("profit_protection", {"r_high": round(r_high,2), "r_now": round(r_now,2)})

    if (cfg.regime_exit_enabled and not regime.get("longs_allowed", True)
            and current < state.entry and r_now <= REGIME_EXIT_R):
        return ExitDecision("market_regime_risk_off", {"r_now": round(r_now,2)})

    if held_minutes >= cfg.max_hold_minutes and r_now < TIME_STOP_MIN_R:
        return ExitDecision("time_stop", {"held_minutes": round(held_minutes,1), "r_now": round(r_now,2)})

    return None
