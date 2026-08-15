"""Universe selection must pick tradeable names without leaking future returns."""
import pytest

from app.backtest.build_universe import qualifies


def bar(close, volume):
    return {"c": close, "v": volume}


def test_a_liquid_in_range_symbol_qualifies():
    bars = [bar(10.0, 1_000_000)] * 5          # $10M/day
    assert qualifies(bars, 2, 30, 5_000_000, 5) is True


def test_too_few_qualifying_days_is_rejected():
    bars = [bar(10.0, 1_000_000)] * 3
    assert qualifies(bars, 2, 30, 5_000_000, 5) is False


def test_a_symbol_below_the_price_band_is_rejected():
    bars = [bar(1.0, 100_000_000)] * 10
    assert qualifies(bars, 2, 30, 5_000_000, 5) is False


def test_a_symbol_above_the_price_band_is_rejected():
    bars = [bar(500.0, 100_000)] * 10
    assert qualifies(bars, 2, 30, 5_000_000, 5) is False


def test_zero_max_price_means_no_upper_cap():
    bars = [bar(500.0, 100_000)] * 10
    assert qualifies(bars, 0.01, 0, 5_000_000, 5) is True


def test_liquidity_is_measured_in_dollars_not_shares():
    """A million shares of a $2 stock is not a million shares of a $30 stock."""
    cheap = [bar(2.0, 1_000_000)] * 10         # $2M/day — too thin
    rich = [bar(30.0, 1_000_000)] * 10         # $30M/day — fine
    assert qualifies(cheap, 2, 30, 5_000_000, 5) is False
    assert qualifies(rich, 2, 30, 5_000_000, 5) is True


def test_a_symbol_that_only_briefly_qualifies_still_counts():
    """A name that entered the band mid-period is exactly what the scanner trades."""
    bars = [bar(80.0, 10_000)] * 20 + [bar(9.0, 2_000_000)] * 5
    assert qualifies(bars, 2, 30, 5_000_000, 5) is True


def test_partial_qualification_below_the_threshold_fails():
    bars = [bar(80.0, 10_000)] * 20 + [bar(9.0, 2_000_000)] * 2
    assert qualifies(bars, 2, 30, 5_000_000, 5) is False


@pytest.mark.parametrize("bars", [
    [], [bar(0, 0)], [bar(10.0, 0)], [bar(0, 1_000_000)],
    [{"c": None, "v": None}], [{}],
])
def test_empty_or_malformed_bars_never_qualify(bars):
    assert qualifies(bars, 2, 30, 5_000_000, 1) is False


def test_selection_does_not_depend_on_price_direction():
    """Filtering on liquidity, not returns, is what keeps this free of lookahead."""
    rising = [bar(5.0, 2_000_000), bar(9.0, 2_000_000), bar(14.0, 2_000_000)]
    falling = [bar(14.0, 2_000_000), bar(9.0, 2_000_000), bar(5.0, 2_000_000)]
    assert qualifies(rising, 2, 30, 5_000_000, 3) == qualifies(falling, 2, 30, 5_000_000, 3) is True
