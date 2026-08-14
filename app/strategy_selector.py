from __future__ import annotations


def classify_strategy(row: dict) -> dict:
    """Classify the setup family without changing execution eligibility.

    The selector is observational first. Once enough backtest/live-paper labels
    exist, individual setup families can be measured independently before any
    family is allowed to alter order decisions.
    """
    change = float(row.get("change_pct") or 0)
    rvol = float(row.get("rvol") or 0)
    ext = abs(float(row.get("vwap_extension_pct") or 0))
    pullback = bool(row.get("pullback_seen"))
    reclaim = bool(row.get("reclaim_confirmed"))
    volume = bool(row.get("volume_confirmed"))
    price = float(row.get("price") or 0)
    vwap = float(row.get("vwap") or 0)
    ema9 = float(row.get("ema9") or 0)
    ema20 = float(row.get("ema20") or 0)

    candidates: list[tuple[str, float, list[str]]] = []

    pull_score = 0.0; pull_reasons=[]
    if pullback: pull_score += 30; pull_reasons.append("controlled_pullback")
    if reclaim: pull_score += 30; pull_reasons.append("vwap_ema_reclaim")
    if volume: pull_score += 20; pull_reasons.append("volume_confirmation")
    if 2 <= rvol <= 8: pull_score += 10; pull_reasons.append("healthy_rvol")
    if ext <= 1.5: pull_score += 10; pull_reasons.append("not_extended")
    candidates.append(("PULLBACK_RECLAIM", pull_score, pull_reasons))

    breakout_score = 0.0; breakout_reasons=[]
    if change >= 8: breakout_score += 25; breakout_reasons.append("strong_day_move")
    if rvol >= 3: breakout_score += 25; breakout_reasons.append("high_rvol")
    if volume: breakout_score += 20; breakout_reasons.append("volume_confirmation")
    if price > vwap > 0 and price > ema9 > ema20 > 0:
        breakout_score += 20; breakout_reasons.append("trend_alignment")
    if ext <= 2.0: breakout_score += 10; breakout_reasons.append("extension_controlled")
    candidates.append(("MOMENTUM_BREAKOUT", breakout_score, breakout_reasons))

    # ORB Retest needs opening-range highs/lows to become a true execution model.
    # For now this is only a provisional profile based on opening-session-like
    # momentum characteristics and never acts as an order gate.
    orb_score = 0.0; orb_reasons=[]
    frac = float(row.get("session_fraction") or 1)
    if frac <= 0.25: orb_score += 25; orb_reasons.append("early_session")
    if change >= 5: orb_score += 20; orb_reasons.append("opening_momentum")
    if rvol >= 3: orb_score += 20; orb_reasons.append("opening_volume")
    if pullback and reclaim: orb_score += 25; orb_reasons.append("retest_characteristics")
    if ext <= 1.5: orb_score += 10; orb_reasons.append("not_chasing")
    candidates.append(("ORB_RETEST_PROVISIONAL", orb_score, orb_reasons))

    candidates.sort(key=lambda x: x[1], reverse=True)
    name, score, reasons = candidates[0]
    confidence = "HIGH" if score >= 80 else ("MEDIUM" if score >= 60 else "LOW")
    return {
        "family": name,
        "fit_score": round(score, 1),
        "confidence": confidence,
        "reasons": reasons,
        "execution_gate": False,
        "alternatives": [{"family": n, "fit_score": round(s,1)} for n,s,_ in candidates[1:]],
    }
