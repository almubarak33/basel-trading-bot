"""Circuit breakers that stop trading after the recent record turns bad.

Ported from the idea behind Freqtrade's `plugins/protections` (StoplossGuard,
MaxDrawdown, LowProfitPairs), rewritten for this bot's data model. No code is
carried over — the trade record, the lock model and the trigger conditions are
ours.

Why it exists: the only global guard here was a daily equity loss limit, and
over 44 backtested sessions it never fired once, while a single exit bucket
(`market_regime_risk_off`) lost $3,514 across 195 trades at −0.47 R apiece. The
damage arrived in instalments too small to move a daily percentage. These guards
measure the recent *record* instead of the day's equity.

One deliberate deviation from Freqtrade: its StoplossGuard counts only stop-type
exits. Here every losing exit counts, because the losses that motivated this were
not stops — they were regime and thesis exits.

Kept IO-free so the live engine and the backtester run the identical rules.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

GLOBAL = "*"


@dataclass(frozen=True)
class ClosedTrade:
    """The minimum a guard needs to judge a finished trade."""
    symbol: str
    closed_at: datetime
    pnl: float
    r_multiple: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class Lock:
    scope: str          # GLOBAL, or a single symbol
    until: datetime
    code: str           # message code, so the UI stays language-neutral
    detail: dict = field(default_factory=dict)

    def covers(self, symbol: str | None) -> bool:
        return self.scope == GLOBAL or (symbol or "").upper() == self.scope


def from_ledger(rows) -> list[ClosedTrade]:
    """Convert the dashboard's round-trip ledger into what the guards read.

    Rows come from `trade_ledger.build_round_trips`, which reconstructs closed
    trades from broker fill activities. Anything without a usable close time is
    dropped rather than guessed at — a guard acting on a wrong timestamp is
    worse than one acting on less history.
    """
    out: list[ClosedTrade] = []
    for row in rows or []:
        stamp = row.get("closed_at")
        if not stamp:
            continue
        try:
            closed_at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if closed_at.tzinfo is None:
            closed_at = closed_at.replace(tzinfo=timezone.utc)
        try:
            pnl = float(row.get("pnl") or 0.0)
        except (TypeError, ValueError):
            continue
        out.append(ClosedTrade(symbol=(row.get("symbol") or "").upper(), closed_at=closed_at,
                               pnl=pnl, reason=str(row.get("reason") or "")))
    return out


def _window(trades, now: datetime, minutes: int, symbol: str | None = None):
    since = now - timedelta(minutes=minutes)
    picked = [t for t in trades if t.closed_at > since]
    if symbol:
        picked = [t for t in picked if t.symbol.upper() == symbol.upper()]
    return sorted(picked, key=lambda t: t.closed_at)


def losing_streak_lock(trades, now: datetime, cfg) -> Lock | None:
    """Too many losing exits in a short window — stand down for a while.

    A run of losses usually means the market has changed rather than that the
    next signal is unlucky, and this bot's own record is the only evidence of
    that available in real time.
    """
    recent = _window(trades, now, cfg.guard_loss_lookback_minutes)
    losers = [t for t in recent if t.pnl < 0]
    if len(losers) < cfg.guard_loss_trades:
        return None
    return Lock(GLOBAL, now + timedelta(minutes=cfg.guard_loss_lock_minutes), "guard_losing_streak",
                {"losses": len(losers), "window_minutes": cfg.guard_loss_lookback_minutes,
                 "r_sum": round(sum(t.r_multiple for t in losers), 2)})


def drawdown_lock(trades, now: datetime, equity: float, cfg) -> Lock | None:
    """Realised drawdown inside a rolling window, measured off the window's peak.

    The daily loss limit compares against the previous close, so a slide that
    starts mid-session and runs into the next one never registers. This walks the
    equity curve of closed trades instead.
    """
    if equity <= 0:
        return None
    recent = _window(trades, now, cfg.guard_drawdown_lookback_minutes)
    if len(recent) < cfg.guard_drawdown_min_trades:
        return None
    running = peak = 0.0
    worst = 0.0
    for trade in recent:
        running += trade.pnl
        peak = max(peak, running)
        worst = min(worst, running - peak)
    drawdown_pct = abs(worst) / equity
    if drawdown_pct < cfg.guard_drawdown_pct:
        return None
    return Lock(GLOBAL, now + timedelta(minutes=cfg.guard_drawdown_lock_minutes), "guard_drawdown",
                {"drawdown_pct": round(drawdown_pct * 100, 2),
                 "limit_pct": round(cfg.guard_drawdown_pct * 100, 2),
                 "window_minutes": cfg.guard_drawdown_lookback_minutes})


def weak_symbol_locks(trades, now: datetime, cfg) -> list[Lock]:
    """Symbols that have repeatedly failed lately get benched individually.

    A name can be structurally broken while the rest of the list is fine; a
    global halt would be the wrong instrument for that.
    """
    locks = []
    recent = _window(trades, now, cfg.guard_symbol_lookback_minutes)
    by_symbol: dict[str, list[ClosedTrade]] = {}
    for trade in recent:
        by_symbol.setdefault(trade.symbol.upper(), []).append(trade)
    for symbol, rows in by_symbol.items():
        if len(rows) < cfg.guard_symbol_trades:
            continue
        total = sum(t.pnl for t in rows)
        if total >= 0:
            continue
        locks.append(Lock(symbol, now + timedelta(minutes=cfg.guard_symbol_lock_minutes),
                          "guard_weak_symbol",
                          {"trades": len(rows), "pnl": round(total, 2),
                           "window_minutes": cfg.guard_symbol_lookback_minutes}))
    return locks


def evaluate(trades, now: datetime, equity: float, cfg) -> list[Lock]:
    """Every lock the current record justifies. Empty means trade freely."""
    if not getattr(cfg, "protections_enabled", True):
        return []
    locks: list[Lock] = []
    for lock in (losing_streak_lock(trades, now, cfg), drawdown_lock(trades, now, equity, cfg)):
        if lock:
            locks.append(lock)
    locks.extend(weak_symbol_locks(trades, now, cfg))
    return locks


def blocking_lock(locks, symbol: str | None, now: datetime) -> Lock | None:
    """The first lock still in force for this symbol, if any."""
    for lock in locks:
        if lock.until > now and lock.covers(symbol):
            return lock
    return None


class ProtectionTracker:
    """Holds locks between checks so a guard keeps its stand-down period.

    Re-evaluating from scratch each pass would release a lock the moment the
    offending trades aged out of the window, which defeats the point of a
    cooling-off period.
    """

    def __init__(self):
        self.locks: list[Lock] = []

    def update(self, trades, now: datetime, equity: float, cfg) -> list[Lock]:
        self.locks = [lock for lock in self.locks if lock.until > now]
        for fresh in evaluate(trades, now, equity, cfg):
            # An identical scope+code already running is not extended; the
            # stand-down is measured from the first trigger, not the latest.
            if not any(l.scope == fresh.scope and l.code == fresh.code for l in self.locks):
                self.locks.append(fresh)
        return self.locks

    def blocked(self, symbol: str | None, now: datetime) -> Lock | None:
        return blocking_lock(self.locks, symbol, now)

    def snapshot(self, now: datetime) -> list[dict]:
        return [{"scope": l.scope, "until": l.until.isoformat(), "code": l.code, "detail": l.detail}
                for l in self.locks if l.until > now]

    def clear(self) -> None:
        self.locks = []
