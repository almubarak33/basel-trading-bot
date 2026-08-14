from app.strategy_selector import classify_strategy


def test_pullback_reclaim_profile():
    row={"change_pct":10,"rvol":4,"vwap_extension_pct":0.8,"pullback_seen":True,
         "reclaim_confirmed":True,"volume_confirmed":True,"price":10.2,"vwap":10.0,
         "ema9":10.1,"ema20":9.9,"session_fraction":0.4}
    out=classify_strategy(row)
    assert out["family"] == "PULLBACK_RECLAIM"
    assert out["fit_score"] >= 80
    assert out["execution_gate"] is False


def test_breakout_profile_when_no_pullback():
    row={"change_pct":15,"rvol":5,"vwap_extension_pct":1.8,"pullback_seen":False,
         "reclaim_confirmed":False,"volume_confirmed":True,"price":10.5,"vwap":10.2,
         "ema9":10.3,"ema20":10.0,"session_fraction":0.5}
    out=classify_strategy(row)
    assert out["family"] == "MOMENTUM_BREAKOUT"
    assert out["execution_gate"] is False
