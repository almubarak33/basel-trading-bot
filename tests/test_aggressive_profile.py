import pytest

from app.strategy import build_candidate, max_spread_for_price, move_in_scope, price_in_scope


def breakout_bars():
    rows=[]
    for i in range(40):
        close=1.0 if i<30 else 1.045
        rows.append({"o":close,"h":close*1.004,"l":close*0.996,"c":close,
                     "v":15_000 if i==39 else 10_000})
    return rows


def test_default_profile_has_no_upper_price_or_move_cap():
    assert price_in_scope(0.01)
    assert price_in_scope(2_500.0)
    assert move_in_scope(250.0)


def test_spread_limit_adapts_to_the_price_band():
    assert max_spread_for_price(0.75) > max_spread_for_price(3.0) > max_spread_for_price(30.0)


def test_momentum_breakout_can_qualify_without_a_prior_pullback():
    snapshot={"latestTrade":{"p":1.045},"latestQuote":{"bp":1.04,"ap":1.05}}
    out=build_candidate("FAST",5.0,3,snapshot,breakout_bars(),
                        avg_daily_volume=500_000,session_fraction=.5)
    assert out.breakout_confirmed is True
    assert out.pullback_seen is False
    assert out.setup == "MOMENTUM_BREAKOUT"
    assert out.eligible is True
    assert out.score >= 72
