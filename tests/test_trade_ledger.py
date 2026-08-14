from app.trade_ledger import build_round_trips


def fill(symbol, side, qty, price, ts):
    return {"symbol":symbol,"side":side,"qty":str(qty),"price":str(price),"transaction_time":ts}


def test_partial_exits_count_as_one_round_trip():
    rows=build_round_trips([
        fill("ABC","buy",100,10.00,"2026-08-14T14:00:00Z"),
        fill("ABC","sell",40,11.00,"2026-08-14T14:30:00Z"),
        fill("ABC","sell",60,12.00,"2026-08-14T15:00:00Z"),
    ])
    assert len(rows)==1
    t=rows[0]
    assert t["symbol"]=="ABC"
    assert t["qty"]==100
    assert t["entry"]==10.0
    assert t["exit"]==11.6
    assert t["pnl"]==160.0
    assert t["pnl_pct"]==16.0


def test_scale_in_weighted_cost_and_flat_close():
    rows=build_round_trips([
        fill("XYZ","buy",50,10.00,"2026-08-14T14:00:00Z"),
        fill("XYZ","buy",50,12.00,"2026-08-14T14:10:00Z"),
        fill("XYZ","sell",100,13.00,"2026-08-14T15:00:00Z"),
    ])
    assert len(rows)==1
    t=rows[0]
    assert t["entry"]==11.0
    assert t["exit"]==13.0
    assert t["pnl"]==200.0


def test_unmatched_sell_is_ignored():
    rows=build_round_trips([
        fill("OLD","sell",10,5.0,"2026-08-14T14:00:00Z"),
    ])
    assert rows==[]
