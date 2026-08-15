from app.stock_data import (
    flatten_corporate_actions,
    price_statistics,
    simulation_chart_bars,
    timeframe_catalog,
)


def test_catalog_exposes_every_requested_price_interval():
    assert [row["value"] for row in timeframe_catalog()] == [
        "1Min", "5Min", "15Min", "30Min", "1Hour",
        "4Hour", "1Day", "1Week", "1Month",
    ]


def test_price_statistics_include_previous_close_and_52_week_range():
    bars = [
        {"t": f"2026-01-{day:02d}T21:00:00Z", "o": day, "h": day + 2,
         "l": day - 0.5, "c": day + 1, "v": day * 1000}
        for day in range(1, 21)
    ]
    stats = price_statistics(bars)

    assert stats["previous_close"] == 20
    assert stats["high_52w"] == 22
    assert stats["low_52w"] == 0.5
    assert stats["average_volume_20d"] == 10_500


def test_corporate_actions_are_flattened_and_sorted_newest_first():
    payload = {"corporate_actions": {
        "reverse_splits": [{"process_date": "2026-02-02", "new_rate": 1, "old_rate": 10}],
        "cash_dividends": [{"ex_date": "2026-03-01", "cash": 0.1}],
    }}

    rows = flatten_corporate_actions(payload)

    assert rows[0]["type"] == "cash_dividend"
    assert rows[1]["type"] == "reverse_split"


def test_simulation_can_draw_every_catalog_timeframe():
    for timeframe in (row["value"] for row in timeframe_catalog()):
        bars = simulation_chart_bars("NOVA", timeframe, 4.82)
        assert len(bars) == 220
        assert bars[0]["t"] < bars[-1]["t"]
        assert all(bar["h"] >= bar["l"] > 0 for bar in bars)
