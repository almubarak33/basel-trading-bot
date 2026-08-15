"""Broker-aware pre-trade controls shared by live and historical execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .alpaca import extract_stop_prices

WORKING_ENTRY_STATUSES = {
    "", "new", "accepted", "pending_new", "partially_filled", "held",
    "accepted_for_bidding", "pending_replace", "calculated",
}


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _walk_orders(orders: Iterable[dict] | None):
    for order in orders or []:
        yield order
        yield from _walk_orders(order.get("legs") or [])


def working_entry_symbols(orders: list[dict] | None) -> set[str]:
    symbols: set[str] = set()
    for order in _walk_orders(orders):
        if str(order.get("side") or "").lower() != "buy":
            continue
        if str(order.get("status") or "").lower() not in WORKING_ENTRY_STATUSES:
            continue
        symbol = str(order.get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)
    return symbols


def _position_symbols(positions: list[dict]) -> set[str]:
    return {str(position.get("symbol") or "").upper() for position in positions if position.get("symbol")}


def _position_notional(position: dict) -> float:
    market_value = abs(_float(position.get("market_value")))
    if market_value > 0:
        return market_value
    qty = abs(_float(position.get("qty")))
    mark = _float(position.get("current_price") or position.get("avg_entry_price"))
    return qty * mark


def _working_entry_notional(orders: list[dict] | None) -> float:
    total = 0.0
    for order in _walk_orders(orders):
        if str(order.get("side") or "").lower() != "buy":
            continue
        if str(order.get("status") or "").lower() not in WORKING_ENTRY_STATUSES:
            continue
        qty = _float(order.get("qty")) - _float(order.get("filled_qty"))
        price = _float(order.get("limit_price") or order.get("stop_price"))
        total += max(qty, 0) * price
    return total


def _portfolio_heat(positions: list[dict], orders: list[dict] | None) -> tuple[float, list[str]]:
    stop_prices = extract_stop_prices(orders or [])
    heat = 0.0
    unprotected: list[str] = []
    position_symbols: set[str] = set()
    for position in positions:
        symbol = str(position.get("symbol") or "").upper()
        if symbol: position_symbols.add(symbol)
        qty = abs(_float(position.get("qty")))
        entry = _float(position.get("avg_entry_price"))
        current = _float(position.get("current_price")) or entry
        stop = stop_prices.get(symbol, 0.0)
        if symbol and qty > 0 and entry > 0:
            if not (0 < stop < current):
                unprotected.append(symbol)
            else:
                heat += max(entry - stop, 0) * qty
    # Working entries already commit future risk. Count their broker stop too,
    # otherwise four pending OTO orders can bypass an aggregate heat ceiling.
    for order in _walk_orders(orders):
        if str(order.get("side") or "").lower() != "buy": continue
        if str(order.get("status") or "").lower() not in WORKING_ENTRY_STATUSES: continue
        symbol = str(order.get("symbol") or "").upper()
        if not symbol or symbol in position_symbols: continue
        qty = max(_float(order.get("qty")) - _float(order.get("filled_qty")), 0)
        entry = _float(order.get("limit_price") or order.get("stop_price"))
        stop = stop_prices.get(symbol, 0.0)
        if qty > 0 and entry > 0:
            if not (0 < stop < entry):
                unprotected.append(symbol)
            else:
                heat += (entry - stop) * qty
    return heat, unprotected


def liquidity_adjusted_quantity(candidate: dict, requested_qty: int, config) -> tuple[int, dict]:
    limits: dict[str, int] = {}
    latest_volume = int(max(_float(candidate.get("latest_bar_volume")), 0))
    average_daily = int(max(_float(candidate.get("avg_daily_volume_20d")), 0))
    if latest_volume > 0:
        limits["bar_participation"] = int(latest_volume * config.max_bar_participation_pct)
    if average_daily > 0:
        limits["daily_participation"] = int(average_daily * config.max_daily_participation_pct)
    positive = [value for value in limits.values() if value > 0]
    quantity = min([requested_qty, *positive]) if positive else requested_qty
    return max(int(quantity), 0), {
        "requested_qty": requested_qty,
        "approved_qty": max(int(quantity), 0),
        "latest_bar_volume": latest_volume,
        "average_daily_volume": average_daily,
        "limits": limits,
    }


@dataclass
class PreTradeDecision:
    allowed: bool
    symbol: str
    requested_qty: int
    approved_qty: int
    blockers: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_pretrade(
    candidate: dict,
    positions: list[dict],
    open_orders: list[dict],
    *,
    equity: float,
    buying_power: float,
    requested_qty: int,
    config,
) -> PreTradeDecision:
    """Evaluate broker state, aggregate risk, buying power and liquidity."""
    symbol = str(candidate.get("symbol") or "").upper()
    entry = _float(candidate.get("entry"))
    stop = _float(candidate.get("stop"))
    blockers: list[str] = []
    position_symbols = _position_symbols(positions)
    entry_symbols = working_entry_symbols(open_orders)
    committed_symbols = position_symbols | entry_symbols

    quality = candidate.get("data_quality") or {}
    if config.require_fresh_market_data and not quality.get("execution_allowed", False):
        blockers.append("market_data_quality")
    if symbol in position_symbols:
        blockers.append("existing_position")
    if symbol in entry_symbols:
        blockers.append("working_entry_order")
    if len(committed_symbols) >= config.max_open_positions and symbol not in committed_symbols:
        blockers.append("max_committed_slots")
    if equity <= 0 or not (entry > stop > 0):
        blockers.append("invalid_risk_inputs")

    heat, unprotected = _portfolio_heat(positions, open_orders)
    if unprotected:
        blockers.append("unprotected_committed_risk")

    approved_qty, liquidity = liquidity_adjusted_quantity(candidate, requested_qty, config)
    if config.require_liquidity_for_orders and not liquidity["limits"]:
        blockers.append("missing_liquidity_measurement")
    if approved_qty < 1:
        blockers.append("insufficient_liquidity_for_one_share")

    candidate_notional = entry * approved_qty
    candidate_heat = max(entry - stop, 0) * approved_qty
    gross = sum(_position_notional(position) for position in positions)
    gross += _working_entry_notional(open_orders)
    projected_gross_pct = (gross + candidate_notional) / equity if equity > 0 else 999.0
    projected_heat_pct = (heat + candidate_heat) / equity if equity > 0 else 999.0
    if projected_gross_pct > config.max_gross_exposure_pct:
        blockers.append("max_gross_exposure")
    if projected_heat_pct > config.max_portfolio_heat_pct:
        blockers.append("max_portfolio_heat")
    if candidate_notional > max(buying_power, 0) * (1 - config.buying_power_buffer_pct):
        blockers.append("insufficient_buying_power")

    blockers = list(dict.fromkeys(blockers))
    return PreTradeDecision(
        allowed=not blockers,
        symbol=symbol,
        requested_qty=requested_qty,
        approved_qty=approved_qty,
        blockers=blockers,
        metrics={
            "committed_slots": len(committed_symbols),
            "max_committed_slots": config.max_open_positions,
            "position_symbols": sorted(position_symbols),
            "working_entry_symbols": sorted(entry_symbols),
            "unprotected_symbols": sorted(unprotected),
            "gross_exposure_pct": round(gross / equity * 100, 3) if equity > 0 else None,
            "projected_gross_exposure_pct": round(projected_gross_pct * 100, 3),
            "portfolio_heat_pct": round(heat / equity * 100, 3) if equity > 0 else None,
            "projected_portfolio_heat_pct": round(projected_heat_pct * 100, 3),
            "candidate_notional": round(candidate_notional, 2),
            "buying_power": round(buying_power, 2),
            "liquidity": liquidity,
            "data_quality": quality,
        },
    )
