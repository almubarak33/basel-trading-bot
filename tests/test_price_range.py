"""The price filter is open by default.

The strategy was built on $2–$30 names, but a $59 stock up 44% was being thrown
away before anything looked at it. The range is now the whole market; the spread
and relative-volume filters are what keep junk out.
"""
import dataclasses

import pytest

from app import strategy
from app.config import settings
from app.strategy import build_candidate


def snapshot(price):
    return {"latestTrade": {"p": price},
            "latestQuote": {"bp": price * 0.9995, "ap": price * 1.0005}}


def bars(price, count=30):
    return [{"o": price, "h": price * 1.002, "l": price * 0.998, "c": price, "v": 10000}
            for _ in range(count)]


def reject_codes(price):
    candidate = build_candidate("AAAA", 10.0, 1, snapshot(price), bars(price),
                                avg_daily_volume=3000, session_fraction=1.0)
    return {entry["code"] for entry in candidate.reject_codes}


def test_the_default_range_spans_the_whole_market():
    """A max of 0 is the no-cap convention, so anything priced above it passes."""
    assert settings.min_price <= 0.01
    assert settings.max_price == 0 or settings.max_price >= 1_000_000


@pytest.mark.parametrize("price", [0.50, 5.0, 59.0, 420.0, 3500.0])
def test_no_price_is_rejected_for_being_out_of_range(price):
    assert "price_out_of_range" not in reject_codes(price)


def test_the_range_is_still_a_real_filter_when_narrowed(monkeypatch):
    """Anyone setting MIN_PRICE/MAX_PRICE must still get the old behaviour."""
    monkeypatch.setattr(strategy, "settings",
                        dataclasses.replace(settings, min_price=2.0, max_price=30.0))
    assert "price_out_of_range" in reject_codes(59.0)
    assert "price_out_of_range" not in reject_codes(11.0)
