"""Construction of broker order payloads."""
from __future__ import annotations
import re
import secrets
from datetime import datetime, timezone
from .pricing import price_string

MAX_CLIENT_ORDER_ID = 128
_UNSAFE = re.compile(r"[^a-z0-9]+")
# كم ندفع فوق/تحت السعر الحالي ليُنفَّذ أمر الجلسة الممتدة. السبريد خارج
# الجلسة الرسمية واسع، وأمر limit بلا هامش قد يبقى معلقاً حتى الإغلاق.
EXTENDED_MARKETABLE_PCT = 0.005


def build_client_order_id(symbol: str, source: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    clean = _UNSAFE.sub("", symbol.lower()) or "sym"
    return f"basel-{source}-{clean}-{stamp}-{secrets.token_hex(3)}"[:MAX_CLIENT_ORDER_ID]


def build_signal_order_id(symbol: str, setup: str, observed_at: datetime | None = None,
                          bucket_minutes: int = 5) -> str:
    """Stable id for one automated signal window.

    A retry after a timeout receives the same id, allowing the broker to reject
    the duplicate instead of silently opening a second position.
    """
    observed_at = observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    bucket_seconds = max(bucket_minutes, 1) * 60
    bucket = int(observed_at.timestamp()) // bucket_seconds
    clean_symbol = _UNSAFE.sub("", symbol.lower()) or "sym"
    clean_setup = _UNSAFE.sub("", setup.lower()) or "setup"
    return f"basel-auto-{clean_symbol}-{clean_setup}-{bucket}"[:MAX_CLIENT_ORDER_ID]


def build_bracket_order(symbol: str, qty: int, entry: float, stop: float, target: float,
                        source: str) -> dict:
    """Legacy fixed-target bracket order, still available for manual experiments."""
    return {
        "symbol": symbol.upper(), "qty": str(qty), "side": "buy", "type": "limit",
        "time_in_force": "day", "limit_price": price_string(entry), "order_class": "bracket",
        "take_profit": {"limit_price": price_string(target)},
        "stop_loss": {"stop_price": price_string(stop)},
        "client_order_id": build_client_order_id(symbol, source),
    }


def build_runner_order(symbol: str, qty: int, entry: float, stop: float, source: str,
                       client_order_id: str | None = None) -> dict:
    """OTO entry with broker-native stop only; Basel Trader manages the upside.

    There is intentionally no fixed take-profit. This allows a strong momentum
    stock to keep running while the autonomous manager protects profits using
    thesis failure, market regime, time-stop and high-water R trailing rules.
    """
    return {
        "symbol": symbol.upper(), "qty": str(qty), "side": "buy", "type": "limit",
        "time_in_force": "day", "limit_price": price_string(entry), "order_class": "oto",
        "stop_loss": {"stop_price": price_string(stop)},
        "client_order_id": client_order_id or build_client_order_id(symbol, source),
    }


def build_extended_hours_entry(symbol: str, qty: int, entry: float, source: str,
                               client_order_id: str | None = None) -> dict:
    """Plain limit buy for the extended session.

    Outside 09:30–16:00 the broker accepts only simple limit day/gtc orders —
    bracket and OTO classes are rejected — so no protective leg can ride along
    with this entry. The stop is enforced by the trade manager in software, and
    that protection lasts only as long as the bot keeps running.
    """
    return {
        "symbol": symbol.upper(), "qty": str(qty), "side": "buy", "type": "limit",
        "time_in_force": "day", "limit_price": price_string(entry),
        "extended_hours": True,
        "client_order_id": client_order_id or build_client_order_id(symbol, source),
    }


def build_extended_hours_exit(symbol: str, qty: int, price: float, source: str = "exit") -> dict:
    """Marketable limit sell for the extended session.

    `DELETE /v2/positions` and any market order are rejected outside the regular
    session, so an extended-hours exit has to be priced. The limit sits below the
    last price by `EXTENDED_MARKETABLE_PCT` to cross a wide after-hours spread.
    """
    limit = max(price * (1 - EXTENDED_MARKETABLE_PCT), 0.0001)
    return {
        "symbol": symbol.upper(), "qty": str(qty), "side": "sell", "type": "limit",
        "time_in_force": "day", "limit_price": price_string(limit),
        "extended_hours": True,
        "client_order_id": build_client_order_id(symbol, source),
    }
