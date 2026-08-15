from datetime import datetime
from zoneinfo import ZoneInfo

from app.chart_data import completed_session_closes

NY = ZoneInfo("America/New_York")


def daily(day, close):
    return {"t":f"{day}T04:00:00Z","c":close}


def test_previous_closes_are_newest_first_and_limited():
    bars=[daily("2026-08-10",10),daily("2026-08-11",11),daily("2026-08-12",12)]
    now=datetime(2026,8,13,10,0,tzinfo=NY)
    assert completed_session_closes(bars,now,limit=2)==[
        {"date":"2026-08-12","close":12.0},{"date":"2026-08-11","close":11.0},
    ]


def test_current_session_close_is_hidden_before_the_bell():
    bars=[daily("2026-08-13",13)]
    assert completed_session_closes(bars,datetime(2026,8,13,15,0,tzinfo=NY))==[]


def test_current_session_close_is_available_after_the_bell():
    bars=[daily("2026-08-13",13)]
    assert completed_session_closes(bars,datetime(2026,8,13,16,1,tzinfo=NY))==[
        {"date":"2026-08-13","close":13.0},
    ]
