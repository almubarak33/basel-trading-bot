"""A moving average must not answer from a window shorter than its own period.

`ema` seeds from the first value in the series. Over a short window the result is
mostly that seed, sitting far below a rising price — which made `price > ema20`
true by construction and quietly disabled every trend filter built on it.
"""
import dataclasses

import pytest

from app import strategy
from app.config import settings
from app.indicators import compute_regime, ema
from app.strategy import build_candidate

RISING = [10 + i * 0.1 for i in range(40)]


# ---- the guard ----------------------------------------------------------

def test_a_short_window_yields_no_average():
    assert ema(RISING[:8], 20) == 0.0


def test_the_average_appears_once_the_period_is_covered():
    assert ema(RISING[:20], 20) > 0


def test_a_shorter_period_is_still_answered_from_the_same_data():
    """Eight bars is plenty for EMA9's sibling; the guard is per-period."""
    assert ema(RISING[:8], 5) > 0


@pytest.mark.parametrize("values", [[], [10.0]])
def test_empty_and_single_point_series_stay_at_zero(values):
    assert ema(values, 20) == 0.0


def test_the_seed_no_longer_drags_the_average_below_the_price():
    """The old behaviour: EMA20 over 8 rising bars trailed the price by ~5%."""
    assert ema(RISING[:8], 20) == 0.0          # would have been ~10.22 against a 10.70 price
    settled = ema(RISING, 20)
    assert settled > RISING[0]


# ---- what the callers do with it ----------------------------------------

def snapshot(price):
    return {"latestTrade": {"p": price}, "latestQuote": {"bp": price * 0.999, "ap": price * 1.001}}


def bars(count, start=1.0, step=0.005):
    return [{"o": start + i * step, "h": start + i * step, "l": start + i * step,
             "c": start + i * step, "v": 12000} for i in range(count)]


def test_a_thin_history_cannot_confirm_a_breakout():
    rows = bars(8)
    out = build_candidate("FAST", 5.0, 3, snapshot(rows[-1]["c"]), rows,
                          avg_daily_volume=500_000, session_fraction=0.5)
    assert out.ema20 == 0.0
    assert out.breakout_confirmed is False
    assert out.reclaim_confirmed is False
    assert out.eligible is False


def test_a_thin_history_is_rejected_for_what_it_actually_is():
    rows = bars(8)
    out = build_candidate("FAST", 5.0, 3, snapshot(rows[-1]["c"]), rows,
                          avg_daily_volume=500_000, session_fraction=0.5)
    assert "insufficient_history" in {e["code"] for e in out.reject_codes}


def test_the_default_floor_covers_ema20():
    assert settings.min_bars >= 20


def test_lowering_the_floor_cannot_reintroduce_the_no_op_filter(monkeypatch):
    """Config alone must not be able to turn the trend check back into a rubber stamp."""
    monkeypatch.setattr(strategy, "settings", dataclasses.replace(settings, min_bars=8))
    rows = bars(8)
    out = build_candidate("FAST", 5.0, 3, snapshot(rows[-1]["c"]), rows,
                          avg_daily_volume=500_000, session_fraction=0.5)
    assert "insufficient_history" not in {e["code"] for e in out.reject_codes}
    assert out.breakout_confirmed is False     # the indicator still refuses
    assert out.eligible is False


def test_the_regime_check_is_unaffected():
    """It already refused under 20 closes, so the guard changes nothing there."""
    healthy = {s: [{"c": c, "h": c, "l": c, "v": 1000} for c in RISING] for s in ("SPY", "QQQ")}
    assert compute_regime(healthy)["longs_allowed"] is True
    thin = {s: [{"c": c, "h": c, "l": c, "v": 1000} for c in RISING[:10]] for s in ("SPY", "QQQ")}
    assert compute_regime(thin)["longs_allowed"] is False
