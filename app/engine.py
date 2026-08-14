from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone, timedelta
from .alpaca import alpaca
from .arming import ArmingTracker
from .config import settings
from .db import log_event
from .scanner import scan
from .session import NY, opening_delay_active
from .strategy import position_size
from .intelligence import enrich_candidate
AUTO_ENABLED = settings.auto_paper_trading
STOP_REQUESTED = False
LAST_SCAN = None
LAST_ERROR = None
LAST_CANDIDATE = None
LAST_RISK_STATUS = None
ARMED = ArmingTracker(lambda kind, symbol, payload: log_event(kind, symbol, json.dumps(payload)))
COOLDOWNS: dict[str, datetime] = {}


def set_auto(enabled: bool):
    global AUTO_ENABLED
    AUTO_ENABLED = bool(enabled)
    log_event("auto_toggle", None, json.dumps({"enabled": AUTO_ENABLED}))
    return AUTO_ENABLED


def state():
    return {
        "auto_enabled": AUTO_ENABLED,
        "last_scan": LAST_SCAN,
        "last_error": LAST_ERROR,
        "last_candidate": LAST_CANDIDATE,
        "last_risk_status": LAST_RISK_STATUS,
        "interval_seconds": settings.scan_interval_seconds,
        "armed_symbols": ARMED.symbols(),
        "cooldown_symbols": list(COOLDOWNS.keys()),
        "entry_model": "INTELLIGENCE_ARM + PULLBACK_RECLAIM_2_STAGE",
    }


def _opening_delay_active() -> bool:
    return opening_delay_active(datetime.now(NY), settings.opening_delay_minutes)


def _cooldown_active(symbol: str) -> bool:
    until = COOLDOWNS.get(symbol)
    if not until: return False
    if datetime.now(timezone.utc) >= until:
        COOLDOWNS.pop(symbol, None); return False
    return True


async def auto_loop():
    global LAST_SCAN, LAST_ERROR, LAST_CANDIDATE, LAST_RISK_STATUS, AUTO_ENABLED
    while not STOP_REQUESTED:
        try:
            if AUTO_ENABLED and settings.paper and alpaca.configured():
                clock = await alpaca.clock()
                if clock.get("is_open", False):
                    LAST_RISK_STATUS = await alpaca.risk_status()
                    if LAST_RISK_STATUS.get("blocked"):
                        AUTO_ENABLED = False
                        ARMED.clear()
                        log_event("daily_loss_guard", None, json.dumps(LAST_RISK_STATUS))
                    elif _opening_delay_active():
                        log_event("opening_delay", None, json.dumps({"minutes": settings.opening_delay_minutes}))
                    else:
                        raw_rows = await scan()
                        rows = [enrich_candidate(r) for r in raw_rows]
                        LAST_SCAN = datetime.now(timezone.utc).isoformat()
                        eligible = [
                            r for r in rows
                            if r.get("eligible") and r.get("decision",{}).get("action") == "ARM"
                        ]
                        eligible.sort(key=lambda r:(r.get("intel_score",0),r.get("score",0),r.get("rvol",0)),reverse=True)
                        LAST_CANDIDATE = eligible[0] if eligible else None
                        log_event("auto_scan", None, json.dumps({"intel_arm_candidates":len(eligible)}))
                        eligible_symbols={r["symbol"].upper() for r in eligible}
                        ARMED.retain_only(eligible_symbols,"intel_or_setup_failed_recheck")
                        if settings.enable_orders:
                            for candidate in eligible[:3]:
                                symbol=candidate["symbol"].upper()
                                if _cooldown_active(symbol): continue
                                if ARMED.arm_or_confirm(candidate):
                                    await maybe_place_paper_order(candidate); break
        except Exception as e:
            LAST_ERROR=str(e); log_event("auto_error",None,json.dumps({"error":LAST_ERROR}))
        await asyncio.sleep(settings.scan_interval_seconds)


async def maybe_place_paper_order(candidate: dict):
    if not settings.paper or not settings.enable_orders: return
    if candidate.get("decision",{}).get("action") != "ARM":
        log_event("order_blocked",candidate.get("symbol"),json.dumps({"reason":"intel_decision_not_arm"})); return
    if _opening_delay_active():
        log_event("order_blocked",candidate.get("symbol"),json.dumps({"reason":"opening_delay"})); return
    risk_status=await alpaca.risk_status()
    if risk_status.get("blocked"):
        log_event("order_blocked",candidate.get("symbol"),json.dumps({"reason":"daily_loss_limit","risk":risk_status})); return

    symbol=candidate["symbol"].upper()
    if _cooldown_active(symbol): return
    positions=await alpaca.positions()
    if len(positions)>=settings.max_open_positions: return
    if any((p.get("symbol") or "").upper()==symbol for p in positions): return

    entry=float(candidate.get("entry") or 0); stop=float(candidate.get("stop") or 0); target=float(candidate.get("target") or 0)
    if not(target>entry>stop>0):
        log_event("order_blocked",symbol,json.dumps({"reason":"invalid_structural_levels"})); return
    risk_pct=((entry-stop)/entry)*100
    if risk_pct>settings.max_stop_pct:
        log_event("order_blocked",symbol,json.dumps({"reason":"stop_too_wide","risk_pct":risk_pct})); return

    account=await alpaca.account(); equity=float(account.get("equity",settings.paper_equity))
    qty=position_size(equity,entry,stop)
    if qty<1: return
    payload={
        "symbol":symbol,"qty":str(qty),"side":"buy","type":"limit","time_in_force":"day",
        "limit_price":str(round(entry,2)),"order_class":"bracket",
        "take_profit":{"limit_price":str(round(target,2))},
        "stop_loss":{"stop_price":str(round(stop,2))},
        "client_order_id":f"basel-intel-{symbol.lower()}",
    }
    result=await alpaca.submit_order(payload)
    COOLDOWNS[symbol]=datetime.now(timezone.utc)+timedelta(minutes=settings.symbol_cooldown_minutes)
    log_event("smart_paper_order",symbol,json.dumps({
        "order":result,
        "setup":candidate.get("setup"),
        "score":candidate.get("score"),
        "intel_score":candidate.get("intel_score"),
        "grade":candidate.get("grade"),
        "rvol":candidate.get("rvol"),
        "entry":entry,"stop":stop,"target":target,"risk_pct":round(risk_pct,2)
    }))
