"""Stops the bot enforces itself, for positions the broker holds no stop for.

Two cases produce an unprotected position:

* an extended-hours entry, because the broker only accepts a plain limit order
  outside the regular session — nothing can be attached to it;
* a regular-session position still open after 16:00, because the stop leg is a
  day order and expires with the bell.

The trade manager watches these prices on every pass instead. That protection
only exists while the bot is running — a crash, a redeploy or a dropped
connection leaves the position naked until the process comes back.
"""
from __future__ import annotations

_STOPS: dict[str, float] = {}


def remember(symbol: str, stop: float) -> None:
    """Record the price below which the position should be closed."""
    key = (symbol or "").upper()
    try: value = float(stop)
    except (TypeError, ValueError): return
    if key and value > 0:
        _STOPS[key] = value


def get(symbol: str) -> float:
    return _STOPS.get((symbol or "").upper(), 0.0)


def forget(symbol: str) -> None:
    _STOPS.pop((symbol or "").upper(), None)


def retain_only(symbols) -> None:
    """Drop stops for symbols that are no longer held."""
    keep = {(s or "").upper() for s in symbols}
    for symbol in list(_STOPS):
        if symbol not in keep:
            _STOPS.pop(symbol, None)


def snapshot() -> dict[str, float]:
    return dict(_STOPS)


def clear() -> None:
    _STOPS.clear()
