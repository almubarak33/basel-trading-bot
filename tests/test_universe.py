"""Point-in-time correctness: a scan must never see data from its own future."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.backtest.config import ExecutionModel
from app.backtest.data import BarStore
from app.backtest.universe import DaySlice, UniverseBuilder, build_snapshot
from app.session import NY

DAY = date(2024, 3, 4)
OPEN = datetime(2024, 3, 4, 9, 30, tzinfo=NY)


def minute_bars(closes, volumes=None, start=OPEN):
    volumes = volumes or [1000] * len(closes)
    bars = []
    previous = closes[0]
    for i, (close, volume) in enumerate(zip(closes, volumes)):
        moment = start + timedelta(minutes=i)
        bars.append({
            "t": moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "o": previous, "h": max(previous, close), "l": min(previous, close), "c": close, "v": volume,
        })
        previous = close
    return bars


def daily_bar(day, close, volume=1_000_000):
    moment = datetime.combine(day, datetime.min.time(), tzinfo=NY)
    return {"t": moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "o": close, "h": close, "l": close, "c": close, "v": volume}


def store_with(symbol="AAAA", closes=(10, 11, 12, 13), prior_close=10.0, volumes=None):
    store = BarStore()
    store.add_minute_bars(symbol, minute_bars(list(closes), volumes))
    store.add_daily_bars(symbol, [daily_bar(DAY - timedelta(days=1), prior_close), daily_bar(DAY, closes[-1])])
    return store


# ---- DaySlice -----------------------------------------------------------

def test_index_at_returns_only_closed_bars():
    day_slice = DaySlice.build("AAAA", minute_bars([10, 11, 12, 13]), 10.0)
    assert day_slice.index_at(OPEN) == 0
    assert day_slice.index_at(OPEN + timedelta(minutes=2)) == 2
    assert day_slice.index_at(OPEN - timedelta(minutes=1)) == -1


def test_window_never_includes_future_bars():
    day_slice = DaySlice.build("AAAA", minute_bars([10, 11, 12, 13]), 10.0)
    window = day_slice.window(day_slice.index_at(OPEN + timedelta(minutes=1)))
    assert [b["c"] for b in window] == [10, 11]


def test_change_pct_is_measured_against_the_prior_session_close():
    day_slice = DaySlice.build("AAAA", minute_bars([10.5, 11.0]), 10.0)
    assert day_slice.change_pct_at(0) == pytest.approx(5.0)
    assert day_slice.change_pct_at(1) == pytest.approx(10.0)


def test_change_pct_ignores_where_the_day_finally_closed():
    """A collapse at 15:59 must not colour a signal taken at 09:31."""
    day_slice = DaySlice.build("AAAA", minute_bars([11.0, 11.5, 4.0]), 10.0)
    assert day_slice.change_pct_at(0) == pytest.approx(10.0)


def test_cumulative_volume_only_counts_elapsed_bars():
    day_slice = DaySlice.build("AAAA", minute_bars([10, 11, 12], [100, 200, 300]), 10.0)
    assert day_slice.volume_at(0) == 100
    assert day_slice.volume_at(1) == 300
    assert day_slice.volume_at(2) == 600


# ---- BarStore -----------------------------------------------------------

def test_trailing_daily_bars_exclude_the_session_being_traded():
    store = store_with()
    trailing = store.trailing_daily_bars("AAAA", DAY, 20)
    assert len(trailing) == 1
    assert trailing[0]["c"] == 10.0


def test_prior_daily_close_ignores_the_current_day():
    assert store_with().prior_daily_close("AAAA", DAY) == 10.0


def test_extended_hours_bars_are_dropped():
    store = BarStore()
    premarket = datetime(2024, 3, 4, 8, 0, tzinfo=NY)
    store.add_minute_bars("AAAA", minute_bars([9.0, 9.1], start=premarket) + minute_bars([10.0]))
    assert len(store.minute_bars("AAAA", DAY)) == 1


def test_store_survives_a_json_round_trip(tmp_path):
    store = store_with()
    path = tmp_path / "bars.json"
    store.to_json(path)
    restored = BarStore.from_json(path)
    assert restored.minute_bars("AAAA", DAY) == store.minute_bars("AAAA", DAY)
    assert restored.prior_daily_close("AAAA", DAY) == 10.0


# ---- screener reconstruction -------------------------------------------

def build_multi_symbol_store():
    store = BarStore()
    # AAAA and BBBB are up on the day; CCCC is *down* but by far the most traded,
    # so it can only reach the universe through the most-actives ranking.
    store.add_minute_bars("AAAA", minute_bars([10.5, 11.0], [100, 100]))
    store.add_minute_bars("BBBB", minute_bars([20.4, 20.8], [100, 100]))
    store.add_minute_bars("CCCC", minute_bars([30.0, 30.0], [9000, 9000]))
    for symbol, prior in (("AAAA", 10.0), ("BBBB", 20.0), ("CCCC", 31.0)):
        store.add_daily_bars(symbol, [daily_bar(DAY - timedelta(days=1), prior)])
    return store


def test_gainers_are_ranked_by_change_at_the_scan_moment():
    builder = UniverseBuilder(build_multi_symbol_store(), DAY, ["AAAA", "BBBB", "CCCC"], 25)
    symbols, change_map, _, _ = builder.select(OPEN, legacy_screener_change=True)
    assert symbols[:2] == ["AAAA", "BBBB"]
    assert round(change_map["AAAA"], 2) == 5.0


def test_most_actives_are_ranked_by_volume_so_far():
    builder = UniverseBuilder(build_multi_symbol_store(), DAY, ["AAAA", "BBBB", "CCCC"], 25)
    _, _, active_rank, _ = builder.select(OPEN, legacy_screener_change=True)
    assert active_rank["CCCC"] == 1


def test_legacy_mode_reproduces_the_hardcoded_zero_change():
    """The old scanner set change_pct=0 for actives that were not also gainers."""
    builder = UniverseBuilder(build_multi_symbol_store(), DAY, ["AAAA", "BBBB", "CCCC"], 25)
    _, change_map, _, _ = builder.select(OPEN, legacy_screener_change=True)
    assert change_map["CCCC"] == 0.0


def test_actives_now_get_their_real_change():
    builder = UniverseBuilder(build_multi_symbol_store(), DAY, ["AAAA", "BBBB", "CCCC"], 25)
    _, change_map, _, _ = builder.select(OPEN, legacy_screener_change=False)
    assert change_map["CCCC"] == pytest.approx(-3.2258, abs=1e-3)


def test_a_strong_mover_pushed_out_of_the_gainers_cut_keeps_its_change():
    """The case the live fix addresses: a symbol reaching the universe only via
    most-actives is still up on the day and must not be reported as flat."""
    store = BarStore()
    # Three risers; a screener_top of 2 leaves the weakest out of the gainers list.
    for symbol, prior, close, volume in (("AAAA", 10.0, 13.0, 100), ("BBBB", 10.0, 12.0, 100),
                                         ("CCCC", 10.0, 10.6, 9000)):
        store.add_minute_bars(symbol, minute_bars([close], [volume]))
        store.add_daily_bars(symbol, [daily_bar(DAY - timedelta(days=1), prior)])

    builder = UniverseBuilder(store, DAY, ["AAAA", "BBBB", "CCCC"], screener_top=2)
    _, fixed, _, _ = builder.select(OPEN, legacy_screener_change=False)
    _, legacy, _, _ = builder.select(OPEN, legacy_screener_change=True)

    assert fixed["CCCC"] == pytest.approx(6.0)
    assert legacy["CCCC"] == 0.0


def test_symbols_with_no_bars_yet_are_not_selected():
    store = build_multi_symbol_store()
    store.add_minute_bars("DDDD", minute_bars([50.0], start=OPEN + timedelta(minutes=90)))
    store.add_daily_bars("DDDD", [daily_bar(DAY - timedelta(days=1), 40.0)])
    builder = UniverseBuilder(store, DAY, ["AAAA", "BBBB", "CCCC", "DDDD"], 25)
    symbols, _, _, _ = builder.select(OPEN, legacy_screener_change=True)
    assert "DDDD" not in symbols


# ---- snapshot synthesis -------------------------------------------------

def test_estimated_spread_widens_as_price_falls():
    execution = ExecutionModel(spread_ticks=1.5, tick_size=0.01, min_spread_pct=0.0)
    cheap = DaySlice.build("AAAA", minute_bars([3.0]), 3.0)
    rich = DaySlice.build("BBBB", minute_bars([30.0]), 30.0)
    cheap_quote = build_snapshot(cheap, 0, execution)["latestQuote"]
    rich_quote = build_snapshot(rich, 0, execution)["latestQuote"]
    cheap_spread = cheap_quote["ap"] - cheap_quote["bp"]
    rich_spread = rich_quote["ap"] - rich_quote["bp"]
    assert round(cheap_spread, 4) == round(rich_spread, 4) == 0.015


def test_snapshot_price_comes_from_the_bar_close():
    day_slice = DaySlice.build("AAAA", minute_bars([10.0, 12.0]), 10.0)
    assert build_snapshot(day_slice, 0, ExecutionModel())["latestTrade"]["p"] == 10.0
