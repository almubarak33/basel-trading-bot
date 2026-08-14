from __future__ import annotations
from datetime import datetime, timezone

from .messages import MessageList, render


def confidence_label(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 85: return "A"
    if score >= 78: return "B"
    if score >= 70: return "C"
    return "D"


def enrich_candidate(row: dict) -> dict:
    x = dict(row)
    price = float(x.get("price") or 0)
    vwap = float(x.get("vwap") or 0)
    ema9 = float(x.get("ema9") or 0)
    ema20 = float(x.get("ema20") or 0)
    rvol = float(x.get("rvol") or 0)
    spread = float(x.get("spread_pct") or 999)
    change = float(x.get("change_pct") or 0)
    risk = float(x.get("risk_pct") or 0)

    technical = 0
    technical += 25 if price > vwap > 0 else 0
    technical += 20 if price > ema9 > ema20 > 0 else 0
    technical += 20 if x.get("pullback_seen") else 0
    technical += 20 if x.get("reclaim_confirmed") else 0
    technical += 15 if x.get("volume_confirmed") else 0

    liquidity = 0
    liquidity += min(55, rvol * 8)
    liquidity += 25 if spread <= .20 else (15 if spread <= .45 else 0)
    liquidity += 20 if 4 <= change <= 22 else (8 if change <= 35 else 0)

    timing = 100
    ext = abs(float(x.get("vwap_extension_pct") or 0))
    onebar = float(x.get("one_bar_move_pct") or 0)
    if ext > 2.5: timing -= 40
    elif ext > 1.5: timing -= 18
    if onebar > 2.5: timing -= 35
    elif onebar > 1.5: timing -= 15
    if not x.get("pullback_seen"): timing -= 25
    timing = max(0, timing)

    risk_quality = max(0, min(100, 100 - max(0, risk - 1.0) * 18))
    if spread > .45: risk_quality -= 20
    risk_quality = max(0, risk_quality)

    composite = round(technical*.35 + liquidity*.25 + timing*.25 + risk_quality*.15, 1)
    x["intel_score"] = composite
    x["grade"] = confidence_label(composite)
    x["components"] = {
        "technical": round(technical,1),
        "liquidity": round(liquidity,1),
        "timing": round(timing,1),
        "risk": round(risk_quality,1),
    }

    bullish=MessageList(); bearish=MessageList()
    if price > vwap > 0: bullish.add("above_vwap")
    if price > ema9 > ema20 > 0: bullish.add("ema_bullish")
    if rvol >= 3: bullish.add("strong_rvol", value=f"{rvol:.1f}x")
    elif rvol >= 2: bullish.add("healthy_rvol", value=f"{rvol:.1f}x")
    if x.get("pullback_seen"): bullish.add("pullback_done")
    if x.get("reclaim_confirmed"): bullish.add("reclaim_done")
    if spread <= .25: bullish.add("tight_spread")

    if ext > 2.5: bearish.add("overextended")
    if change > 25: bearish.add("large_move")
    if spread > .45: bearish.add("wide_spread")
    if rvol < 2: bearish.add("weak_rvol")
    if not x.get("pullback_seen"): bearish.add("no_clean_pullback")
    if not x.get("reclaim_confirmed"): bearish.add("reclaim_missing")

    x["bull_case"] = bullish.texts()
    x["bear_case"] = bearish.texts()
    x["bull_codes"] = bullish.codes
    x["bear_codes"] = bearish.codes
    if x.get("eligible") and composite >= 85:
        action="ARM"; thesis_code="thesis_arm"
    elif composite >= 75:
        action="WATCH"; thesis_code="thesis_watch"
    else:
        action="AVOID"; thesis_code="thesis_avoid"
    x["decision"]={"action":action,"thesis":render(thesis_code),"thesis_code":thesis_code,"confidence":x["grade"]}

    # Preserve verified/diagnostic catalyst data supplied by the live scanner.
    # Historical backtests intentionally keep it unavailable until historical
    # news is replayed point-in-time, avoiding look-ahead bias.
    if "catalyst" not in x:
        x["catalyst"]={"status":"UNVERIFIED","headline":None,"note":render("catalyst_missing"),"note_code":"catalyst_missing","execution_gate":False}
    x["insider"]={"status":"UNVERIFIED","activity":None,"note":render("insider_missing"),"note_code":"insider_missing"}
    x["updated_at"]=datetime.now(timezone.utc).isoformat()
    return x


def market_brief(status: dict) -> dict:
    regime=status.get("market_regime") or {}
    healthy=int(regime.get("healthy_indexes") or 0)
    if healthy>=2:
        tone="RISK_ON"; code="brief_risk_on"
    elif healthy==1:
        tone="MIXED"; code="brief_mixed"
    else:
        tone="RISK_OFF"; code="brief_risk_off"
    return {"tone":tone,"text":render(code),"text_code":code,"regime":regime}
