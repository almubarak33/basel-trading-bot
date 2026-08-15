from app.arming import ArmingTracker


def candidate(symbol="AAAA", price=10.0, score=90.0, intel=91.0, setup="PULLBACK_RECLAIM"):
    return {"symbol": symbol, "price": price, "score": score, "intel_score": intel,
            "grade": "A+", "setup": setup,
            "data_quality": {"execution_allowed": True}}


def test_first_sighting_only_arms():
    tracker = ArmingTracker()
    assert tracker.arm_or_confirm(candidate()) is False
    assert tracker.symbols() == ["AAAA"]


def test_second_sighting_confirms_and_clears():
    tracker = ArmingTracker()
    tracker.arm_or_confirm(candidate())
    assert tracker.arm_or_confirm(candidate()) is True
    assert tracker.symbols() == []


def test_price_running_away_disarms_instead_of_confirming():
    tracker = ArmingTracker()
    tracker.arm_or_confirm(candidate(price=10.0))
    # +1.5% is beyond the 1% chase tolerance.
    assert tracker.arm_or_confirm(candidate(price=10.15)) is False
    assert tracker.symbols() == []


def test_small_drift_still_confirms():
    tracker = ArmingTracker()
    tracker.arm_or_confirm(candidate(price=10.0))
    assert tracker.arm_or_confirm(candidate(price=10.05)) is True


def test_score_collapse_disarms_instead_of_confirming():
    tracker = ArmingTracker()
    tracker.arm_or_confirm(candidate(score=92, intel=93))
    assert tracker.arm_or_confirm(candidate(score=80, intel=81)) is False
    assert tracker.symbols() == []


def test_setup_family_must_be_stable_across_confirmations():
    tracker = ArmingTracker()
    tracker.arm_or_confirm(candidate(setup="PULLBACK_RECLAIM"))
    assert tracker.arm_or_confirm(candidate(setup="MOMENTUM_BREAKOUT")) is False
    assert tracker.symbols() == []


def test_bad_market_data_disarms_the_signal():
    tracker = ArmingTracker()
    tracker.arm_or_confirm(candidate())
    degraded = candidate()
    degraded["data_quality"] = {"execution_allowed": False}
    assert tracker.arm_or_confirm(degraded) is False
    assert tracker.symbols() == []


def test_retain_only_disarms_missing_symbols():
    tracker = ArmingTracker()
    tracker.arm_or_confirm(candidate("AAAA"))
    tracker.arm_or_confirm(candidate("BBBB"))
    tracker.retain_only({"AAAA"}, "gone")
    assert tracker.symbols() == ["AAAA"]


def test_events_are_reported_to_the_callback():
    seen = []
    tracker = ArmingTracker(lambda kind, symbol, payload: seen.append((kind, symbol)))
    tracker.arm_or_confirm(candidate())
    tracker.retain_only(set(), "gone")
    assert seen == [("setup_armed", "AAAA"), ("setup_disarmed", "AAAA")]
