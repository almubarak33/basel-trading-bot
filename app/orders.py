"""Construction of broker order payloads."""
from __future__ import annotations
import re
import secrets
from datetime import datetime, timezone

MAX_CLIENT_ORDER_ID = 128
_UNSAFE = re.compile(r"[^a-z0-9]+")


def build_client_order_id(symbol: str, source: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    clean = _UNSAFE.sub("", symbol.lower()) or "sym"
    return f"basel-{source}-{clean}-{stamp}-{secrets.token_hex(3)}"[:MAX_CLIENT_ORDER_ID]


def build_bracket_order(symbol: str, qty: int, entry: float, stop: float, target: float,
                        source: str) -> dict:
    """Legacy fixed-target bracket order, still available for manual experiments."""
    return {
        "symbol": symbol.upper(), "qty": str(qty), "side": "buy", "type": "limit",
        "time_in_force": "day", "limit_price": str(round(entry, 2)), "order_class": "bracket",
        "take_profit": {"limit_price": str(round(target, 2))},
        "stop_loss": {"stop_price": str(round(stop, 2))},
        "client_order_id": build_client_order_id(symbol, source),
    }


def build_runner_order(symbol: str, qty: int, entry: float, stop: float, source: str) -> dict:
    """OTO entry with broker-native stop only; Basel Trader manages the upside.

    There is intentionally no fixed take-profit. This allows a strong momentum
    stock to keep running while the autonomous manager protects profits using
    thesis failure, market regime, time-stop and high-water R trailing rules.
    """
    return {
        "symbol": symbol.upper(), "qty": str(qty), "side": "buy", "type": "limit",
        "time_in_force": "day", "limit_price": str(round(entry, 2)), "order_class": "oto",
        "stop_loss": {"stop_price": str(round(stop, 2))},
        "client_order_id": build_client_order_id(symbol, source),
    }
