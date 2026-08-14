from app.microstructure import analyze_microstructure


def test_supportive_tight_market():
    out=analyze_microstructure(
        {"bp":10.00,"ap":10.01,"bs":1800,"as":900},
        {"p":10.01},10.01,
    )
    assert out["state"] == "SUPPORTIVE"
    assert out["spread_pct"] < 0.15
    assert out["displayed_imbalance"] > 0
    assert out["execution_gate"] is False


def test_fragile_wide_market():
    out=analyze_microstructure(
        {"bp":9.80,"ap":10.20,"bs":50,"as":600},
        {"p":9.81},10.0,
    )
    assert out["state"] == "FRAGILE"
    assert out["quality_score"] < 50


def test_missing_quote_is_safe():
    out=analyze_microstructure({}, {"p":5.0},5.0)
    assert out["state"] in {"NEUTRAL","FRAGILE"}
    assert out["spread_pct"] is None
    assert out["execution_gate"] is False
