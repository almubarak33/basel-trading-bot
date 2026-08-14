"""Two-stage entry confirmation, shared by the live engine and the backtester.

A setup must survive two consecutive scans before it becomes tradeable, and it is
disarmed if price runs away from the level that first armed it (anti-chase).
"""
from __future__ import annotations
from typing import Callable

# Percent the price may drift above the arming price before the setup is considered chased.
MAX_ARM_DRIFT_PCT = 1.0
REQUIRED_CONFIRMATIONS = 2


class ArmingTracker:
    """Per-symbol arming state. One instance per engine; the backtester gets its own."""

    def __init__(self, on_event: Callable[[str, str | None, dict], None] | None = None):
        self._armed: dict[str, dict] = {}
        self._on_event = on_event or (lambda kind, symbol, payload: None)

    def symbols(self) -> list[str]:
        return list(self._armed.keys())

    def clear(self) -> None:
        self._armed.clear()

    def retain_only(self, symbols: set[str], reason: str) -> None:
        """Disarm anything that no longer passes the current scan."""
        for symbol in list(self._armed.keys()):
            if symbol not in symbols:
                self._armed.pop(symbol, None)
                self._on_event("setup_disarmed", symbol, {"reason": reason})

    def arm_or_confirm(self, candidate: dict) -> bool:
        """Return True only when the setup has been confirmed enough times to trade."""
        symbol = candidate["symbol"].upper()
        current = self._armed.get(symbol)
        if current is None:
            self._armed[symbol] = {
                "count": 1,
                "first_price": float(candidate["price"]),
                "first_score": float(candidate["score"]),
                "intel_score": float(candidate.get("intel_score") or 0),
                "grade": candidate.get("grade"),
            }
            self._on_event("setup_armed", symbol, dict(self._armed[symbol]))
            return False

        first_price = float(current.get("first_price", candidate["price"]))
        now_price = float(candidate["price"])
        if first_price > 0 and (now_price/first_price-1)*100 > MAX_ARM_DRIFT_PCT:
            self._armed.pop(symbol, None)
            self._on_event("setup_disarmed", symbol, {"reason": "price_ran_away"})
            return False

        current["count"] = int(current.get("count", 1)) + 1
        current["latest_score"] = float(candidate["score"])
        current["latest_intel_score"] = float(candidate.get("intel_score") or 0)
        if current["count"] >= REQUIRED_CONFIRMATIONS:
            self._armed.pop(symbol, None)
            return True
        return False
