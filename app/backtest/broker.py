"""Simulated broker: limit-order fills, bracket exits, and portfolio accounting."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

from ..exits import PositionState
from .config import ExecutionModel


@dataclass
class PendingOrder:
    symbol: str
    limit: float
    stop: float
    target: float
    qty: int
    placed_at: datetime
    fixed_target: bool = True
    meta: dict = field(default_factory=dict)
    bars_waited: int = 0


@dataclass
class OpenPosition:
    symbol: str
    entry_price: float
    qty: int
    stop: float
    target: float
    entry_time: datetime
    state: PositionState
    meta: dict = field(default_factory=dict)

    @property
    def risk_per_share(self) -> float:
        return max(self.entry_price - self.stop, 0.01)


@dataclass
class ClosedTrade:
    symbol: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    qty: int
    stop: float
    target: float
    reason: str
    pnl: float
    r_multiple: float
    meta: dict = field(default_factory=dict)


class SimulatedBroker:
    def __init__(self, starting_equity: float, execution: ExecutionModel):
        self.cash = starting_equity
        self.execution = execution
        self.pending: dict[str, PendingOrder] = {}
        self.positions: dict[str, OpenPosition] = {}
        self.trades: list[ClosedTrade] = []
        self.cancelled = 0

    # ---- portfolio -------------------------------------------------------
    def equity(self, marks: dict[str, float]) -> float:
        held = sum(p.qty * marks.get(p.symbol, p.entry_price) for p in self.positions.values())
        return self.cash + held

    def exposure_symbols(self) -> set[str]:
        """Symbols already committed — an open position or a working order."""
        return set(self.positions) | set(self.pending)

    def slot_count(self) -> int:
        return len(self.positions) + len(self.pending)

    # ---- order lifecycle -------------------------------------------------
    def place(self, order: PendingOrder) -> None:
        self.pending[order.symbol] = order

    def cancel(self, symbol: str) -> None:
        if self.pending.pop(symbol, None) is not None:
            self.cancelled += 1

    def process_bar(self, symbol: str, bar: dict, now: datetime, use_true_initial_risk: bool) -> ClosedTrade | None:
        """Advance one symbol by one bar: bracket exits first, then pending fills.

        A position is only managed from the bar *after* its fill, so a single bar
        never both opens and closes a trade.
        """
        if symbol in self.positions:
            return self._check_bracket(symbol, bar, now)
        if symbol in self.pending:
            self._try_fill(symbol, bar, now, use_true_initial_risk)
        return None

    def _try_fill(self, symbol: str, bar: dict, now: datetime, use_true_initial_risk: bool) -> None:
        order = self.pending[symbol]
        low = float(bar.get("l") or 0)
        open_price = float(bar.get("o") or 0)

        if low > 0 and low <= order.limit:
            # A buy limit fills at the limit, or better if the bar opened below it.
            fill = min(order.limit, open_price) if open_price > 0 else order.limit
            cost = fill * order.qty
            if cost > self.cash:
                self.cancel(symbol)
                return
            self.cash -= cost
            self.pending.pop(symbol)
            risk = max(fill - order.stop, 0.01)
            self.positions[symbol] = OpenPosition(
                symbol=symbol, entry_price=fill, qty=order.qty, stop=order.stop, target=order.target,
                entry_time=now, meta={**order.meta, "fixed_target": order.fixed_target},
                state=PositionState(symbol=symbol, entry=fill, first_seen=now, high=fill,
                                    initial_risk_per_share=risk if use_true_initial_risk else None),
            )
            return

        order.bars_waited += 1
        if order.bars_waited >= self.execution.entry_timeout_bars:
            self.cancel(symbol)

    def _check_bracket(self, symbol: str, bar: dict, now: datetime) -> ClosedTrade | None:
        position = self.positions[symbol]
        high = float(bar.get("h") or 0)
        low = float(bar.get("l") or 0)
        open_price = float(bar.get("o") or 0)

        stop_hit = low > 0 and low <= position.stop
        target_hit = bool(position.meta.get("fixed_target", True)) and high > 0 and high >= position.target

        if stop_hit and (not target_hit or self.execution.same_bar_stop_first):
            # Stops become market orders: a gap-down fills at the open, and even a
            # clean trigger pays slippage.
            raw = min(open_price, position.stop) if open_price > 0 else position.stop
            fill = raw * (1 - self.execution.stop_slippage_bps / 10_000)
            return self.close(symbol, fill, now, "stop_loss")
        if target_hit:
            fill = max(open_price, position.target) if open_price > 0 else position.target
            return self.close(symbol, fill, now, "take_profit")
        return None

    def close(self, symbol: str, price: float, now: datetime, reason: str, meta: dict | None = None) -> ClosedTrade:
        position = self.positions.pop(symbol)
        self.cash += price * position.qty
        pnl = (price - position.entry_price) * position.qty
        trade = ClosedTrade(
            symbol=symbol, entry_time=position.entry_time, entry_price=position.entry_price,
            exit_time=now, exit_price=price, qty=position.qty, stop=position.stop, target=position.target,
            reason=reason, pnl=pnl,
            r_multiple=(price - position.entry_price) / position.risk_per_share,
            meta={**position.meta, **(meta or {})},
        )
        self.trades.append(trade)
        return trade
