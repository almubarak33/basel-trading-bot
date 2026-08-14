"""Construction of broker order payloads.

Both the autonomous engine and the manual endpoint submit the same bracket
order, so the shape lives here once rather than being written out twice.
"""
from __future__ import annotations
import re
import secrets
from datetime import datetime, timezone

# Alpaca caps client_order_id at 128 characters and expects a plain token.
MAX_CLIENT_ORDER_ID = 128
_UNSAFE = re.compile(r"[^a-z0-9]+")


def build_client_order_id(symbol: str, source: str) -> str:
    """A fresh id for every submission.

    Alpaca rejects a client_order_id it has already seen, so deriving it from
    the symbol alone meant the first order for a symbol permanently blocked
    every later one. The timestamp makes the id readable in logs and the random
    suffix removes any chance of a collision within the same second.

    This is deliberately not an idempotency key: nothing here retries a
    submission, and reusing an id would resurrect the original bug.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    clean = _UNSAFE.sub("", symbol.lower()) or "sym"
    return f"basel-{source}-{clean}-{stamp}-{secrets.token_hex(3)}"[:MAX_CLIENT_ORDER_ID]


def build_bracket_order(symbol: str, qty: int, entry: float, stop: float, target: float,
                        source: str) -> dict:
    """A day limit entry with attached take-profit and stop-loss legs."""
    return {
        "symbol": symbol.upper(),
        "qty": str(qty),
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": str(round(entry, 2)),
        "order_class": "bracket",
        "take_profit": {"limit_price": str(round(target, 2))},
        "stop_loss": {"stop_price": str(round(stop, 2))},
        "client_order_id": build_client_order_id(symbol, source),
    }
