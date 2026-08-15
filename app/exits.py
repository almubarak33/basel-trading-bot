"""Pure exit-decision logic, shared by the live trade manager and backtester."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from .indicators import ema, num, vwap

FALLBACK_RISK_PCT = 0.015
MIN_BARS_FOR_MANAGEMENT = 20
REGIME_EXIT_R = -0.35
TIME_STOP_MIN_R = 0.5

@dataclass
class PositionState:
    symbol: str
    entry: float
    first_seen: datetime
    high: float
    fail_checks: int = 0
    runner_fail_checks: int = 0
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
    closes = [num(b.get("c")) for b in bars if num(b.get("c")) > 0]
    if len(closes) < MIN_BARS_FOR_MANAGEMENT or state.entry <= 0 or current <= 0:
        return None

    ema9 = ema(closes[-80:], 9)
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

    # Runner mode keeps 2R as a measuring reference, never a hard sell order.
    # A giveback only becomes an exit after short-term price structure confirms
    # the reversal on consecutive manager checks.
    profit_exit: tuple[str, dict] | None = None
    if getattr(cfg, "runner_mode", True) and r_high >= getattr(cfg, "runner_activate_r", 2.0):
        giveback = min(max(getattr(cfg, "runner_giveback_fraction", 0.35), 0.10), 0.80)
        floor = max(getattr(cfg, "runner_min_lock_r", 1.0), r_high * (1 - giveback))
        if r_now <= floor:
            profit_exit = ("runner_trailing_exit", {
                "r_high": round(r_high, 2), "r_now": round(r_now, 2),
                "locked_floor_r": round(floor, 2),
            })

    if profit_exit is None and r_high >= cfg.protect_profit_after_r and r_now <= cfg.protected_floor_r:
        profit_exit = ("profit_protection", {
            "r_high": round(r_high, 2), "r_now": round(r_now, 2),
        })

    latest_bar_falling = len(closes) >= 2 and closes[-1] < closes[-2]
    reversal_confirmed = current < ema9 and latest_bar_falling
    state.runner_fail_checks = state.runner_fail_checks + 1 if profit_exit and reversal_confirmed else 0
    checks_required = max(int(getattr(cfg, "runner_exit_checks", 2)), 1)
    if profit_exit and state.runner_fail_checks >= checks_required:
        reason, meta = profit_exit
        return ExitDecision(reason, {
            **meta, "ema9": round(ema9, 4),
            "reversal_checks": state.runner_fail_checks,
        })

    if (cfg.regime_exit_enabled and not regime.get("longs_allowed", True)
            and current < state.entry and r_now <= REGIME_EXIT_R):
        return ExitDecision("market_regime_risk_off", {"r_now": round(r_now,2)})

    if held_minutes >= cfg.max_hold_minutes and r_now < TIME_STOP_MIN_R:
        return ExitDecision("time_stop", {"held_minutes": round(held_minutes,1), "r_now": round(r_now,2)})

    return None
