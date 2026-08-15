from datetime import datetime, timedelta, timezone

from app.data_quality import assess_market_data, parse_timestamp


NOW = datetime(2024, 3, 4, 15, 0, tzinfo=timezone.utc)


def market_payload(age_seconds=0):
    stamp=(NOW-timedelta(seconds=age_seconds)).isoformat()
    bars=[{"t":stamp,"o":10.0,"h":10.2,"l":9.9,"c":10.1,"v":1000}]
    snapshot={"latestTrade":{"p":10.1,"t":stamp},
              "latestQuote":{"bp":10.09,"ap":10.11,"t":stamp},
              "minuteBar":bars[-1]}
    return snapshot,bars


def test_fresh_consistent_data_passes():
    snapshot,bars=market_payload()
    quality=assess_market_data(snapshot,bars,observed_at=NOW)
    assert quality["execution_allowed"] is True
    assert quality["status"] == "GOOD"


def test_stale_quote_and_trade_block_execution():
    snapshot,bars=market_payload(age_seconds=200)
    quality=assess_market_data(snapshot,bars,observed_at=NOW,max_quote_age_seconds=90)
    assert quality["execution_allowed"] is False
    assert "stale_realtime_data" in quality["blockers"]


def test_crossed_quote_blocks_execution():
    snapshot,bars=market_payload()
    snapshot["latestQuote"].update(bp=10.2,ap=10.1)
    quality=assess_market_data(snapshot,bars,observed_at=NOW)
    assert "crossed_quote" in quality["blockers"]


def test_malformed_candle_blocks_execution():
    snapshot,bars=market_payload()
    bars[-1]["h"]=9.5
    quality=assess_market_data(snapshot,bars,observed_at=NOW)
    assert "malformed_ohlc" in quality["blockers"]


def test_missing_timestamps_are_not_accepted_for_point_in_time_trading():
    snapshot,bars=market_payload()
    snapshot["latestTrade"].pop("t")
    snapshot["latestQuote"].pop("t")
    quality=assess_market_data(snapshot,bars,observed_at=NOW)
    assert "missing_realtime_timestamp" in quality["blockers"]


def test_timestamp_parser_supports_zulu_and_nanoseconds():
    assert parse_timestamp("2024-03-04T15:00:00Z") == NOW
    assert parse_timestamp(int(NOW.timestamp()*1_000_000_000)) == NOW
