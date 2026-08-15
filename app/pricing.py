"""US-equity price precision shared by strategy levels and broker orders."""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


def price_decimals(value: float) -> int:
    return 4 if 0 < abs(float(value)) < 1 else 2


def round_price(value: float) -> float:
    quantum=Decimal("0.0001") if price_decimals(value)==4 else Decimal("0.01")
    return float(Decimal(str(value)).quantize(quantum,rounding=ROUND_HALF_UP))


def price_string(value: float) -> str:
    return str(round_price(value))
