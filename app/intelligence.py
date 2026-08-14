from __future__ import annotations
from datetime import datetime, timezone


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
    score = float(x.get("score") or 0)
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

    bullish=[]; bearish=[]
    if price > vwap > 0: bullish.append("Price above VWAP")
    if price > ema9 > ema20 > 0: bullish.append("EMA structure bullish")
    if rvol >= 3: bullish.append(f"Strong RVOL {rvol:.1f}x")
    elif rvol >= 2: bullish.append(f"Healthy RVOL {rvol:.1f}x")
    if x.get("pullback_seen"): bullish.append("Controlled pullback completed")
    if x.get("reclaim_confirmed"): bullish.append("Reclaim confirmed")
    if spread <= .25: bullish.append("Tight spread")

    if ext > 2.5: bearish.append("Overextended above VWAP")
    if change > 25: bearish.append("Large day move; reversal risk elevated")
    if spread > .45: bearish.append("Wide spread")
    if rvol < 2: bearish.append("Weak relative volume")
    if not x.get("pullback_seen"): bearish.append("No clean pullback yet")
    if not x.get("reclaim_confirmed"): bearish.append("Reclaim not confirmed")

    x["bull_case"] = bullish
    x["bear_case"] = bearish
    if x.get("eligible") and composite >= 85:
        action="ARM"
        thesis="High-quality momentum setup. Wait for second confirmation; do not chase."
    elif composite >= 75:
        action="WATCH"
        thesis="Promising setup, but timing or risk quality is not yet strong enough."
    else:
        action="AVOID"
        thesis="Current reward/risk or entry timing does not justify a trade."
    x["decision"]={"action":action,"thesis":thesis,"confidence":x["grade"]}
    x["catalyst"]={"status":"UNVERIFIED","headline":None,"note":"News/catalyst provider not connected yet."}
    x["insider"]={"status":"UNVERIFIED","activity":None,"note":"SEC insider feed not connected yet."}
    x["updated_at"]=datetime.now(timezone.utc).isoformat()
    return x


def market_brief(status: dict) -> dict:
    regime=status.get("market_regime") or {}
    healthy=int(regime.get("healthy_indexes") or 0)
    if healthy>=2:
        tone="RISK_ON"; text="SPY and QQQ are supportive of long momentum setups."
    elif healthy==1:
        tone="MIXED"; text="Broad market confirmation is mixed; demand higher-quality entries."
    else:
        tone="RISK_OFF"; text="Broad market is not supportive; new long entries should be blocked or rare."
    return {"tone":tone,"text":text,"regime":regime}
