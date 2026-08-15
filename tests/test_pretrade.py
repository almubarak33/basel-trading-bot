import dataclasses

from app.config import settings
from app.pretrade import evaluate_pretrade, working_entry_symbols


CONFIG=dataclasses.replace(
    settings,max_open_positions=4,max_gross_exposure_pct=.60,max_portfolio_heat_pct=.02,
    max_bar_participation_pct=.05,max_daily_participation_pct=.001,
    buying_power_buffer_pct=.05,require_liquidity_for_orders=True,
    require_fresh_market_data=True,
)


def candidate(symbol="AAAA"):
    return {"symbol":symbol,"entry":10.0,"stop":9.5,"latest_bar_volume":1000,
            "avg_daily_volume_20d":1_000_000,
            "data_quality":{"execution_allowed":True,"status":"GOOD"}}


def stop_order(symbol="BBBB",stop=9.5):
    return {"symbol":symbol,"side":"sell","type":"stop","status":"new","stop_price":stop}


def position(symbol="BBBB",qty=100,entry=10.0):
    return {"symbol":symbol,"qty":qty,"avg_entry_price":entry,
            "current_price":entry,"market_value":qty*entry}


def decide(row=None,positions=None,orders=None,requested=100,buying_power=20_000):
    return evaluate_pretrade(
        row or candidate(),positions or [],orders or [],equity=20_000,
        buying_power=buying_power,requested_qty=requested,config=CONFIG,
    )


def test_happy_path_caps_quantity_to_five_percent_of_the_latest_bar():
    result=decide()
    assert result.allowed is True
    assert result.approved_qty == 50
    assert result.metrics["liquidity"]["limits"]["bar_participation"] == 50


def test_working_entries_are_detected_but_protective_stops_are_not():
    orders=[{"symbol":"AAAA","side":"buy","type":"limit","status":"new"},stop_order()]
    assert working_entry_symbols(orders) == {"AAAA"}


def test_duplicate_working_entry_is_blocked_after_a_restart():
    order={"symbol":"AAAA","side":"buy","type":"limit","status":"accepted",
           "qty":10,"filled_qty":0,"limit_price":10}
    result=decide(orders=[order])
    assert result.allowed is False
    assert "working_entry_order" in result.blockers


def test_pending_entries_count_toward_the_portfolio_slot_limit():
    orders=[]
    for index in range(4):
        orders.append({"symbol":f"P{index}","side":"buy","type":"limit","status":"new",
                       "qty":10,"filled_qty":0,"limit_price":10})
    result=decide(orders=orders)
    assert "max_committed_slots" in result.blockers


def test_an_unprotected_existing_position_blocks_more_risk():
    result=decide(positions=[position()],orders=[])
    assert "unprotected_committed_risk" in result.blockers


def test_a_protected_position_contributes_to_portfolio_heat():
    result=decide(positions=[position()],orders=[stop_order()])
    assert result.allowed is True
    assert result.metrics["projected_portfolio_heat_pct"] == 0.375


def test_a_profit_locking_stop_above_entry_is_protected_with_zero_heat():
    protected=position(entry=10.0)
    protected["current_price"]=11.0
    result=decide(positions=[protected],orders=[stop_order(stop=10.5)])
    assert result.allowed is True
    assert result.metrics["projected_portfolio_heat_pct"] == 0.125


def test_a_pending_oto_order_also_contributes_to_portfolio_heat():
    parent={"symbol":"PEND","side":"buy","type":"limit","status":"new",
            "qty":100,"filled_qty":0,"limit_price":10,
            "legs":[stop_order("PEND",9.5)]}
    result=decide(orders=[parent])
    assert result.allowed is True
    assert result.metrics["projected_portfolio_heat_pct"] == 0.375


def test_bad_market_data_never_reaches_the_broker():
    row=candidate(); row["data_quality"]={"execution_allowed":False,"blockers":["stale_realtime_data"]}
    assert "market_data_quality" in decide(row=row).blockers


def test_buying_power_buffer_is_enforced():
    result=decide(requested=100,buying_power=400)
    assert "insufficient_buying_power" in result.blockers
