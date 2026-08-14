from __future__ import annotations
import asyncio, json
from datetime import datetime, timezone
from .alpaca import alpaca
from .config import settings
from .db import log_event

TRACKED: dict[str, dict] = {}
LAST_RUN = None
LAST_ERROR = None
LAST_ACTION = None


def state():
    return {"enabled": settings.auto_manage_positions,"last_run":LAST_RUN,"last_error":LAST_ERROR,"last_action":LAST_ACTION,"tracked":TRACKED}


def _ema(values,n):
    if not values:return 0.0
    k=2/(n+1); out=values[0]
    for v in values[1:]: out=v*k+out*(1-k)
    return out


def _vwap(bars):
    pv=vol=0.0
    for b in bars:
        v=float(b.get("v") or 0); c=float(b.get("c") or 0); h=float(b.get("h") or c); l=float(b.get("l") or c)
        if v<=0: continue
        pv+=((h+l+c)/3)*v; vol+=v
    return pv/vol if vol else 0.0


async def _close(symbol, reason, meta=None):
    global LAST_ACTION
    result=await alpaca.close_position(symbol)
    LAST_ACTION={"symbol":symbol,"action":"CLOSE","reason":reason,"ts":datetime.now(timezone.utc).isoformat()}
    payload={"reason":reason,"result":result}
    if meta: payload.update(meta)
    log_event("auto_exit",symbol,json.dumps(payload))
    TRACKED.pop(symbol,None)


async def manage_once():
    global LAST_RUN, LAST_ERROR
    LAST_RUN=datetime.now(timezone.utc).isoformat(); LAST_ERROR=None
    if not (settings.paper and settings.enable_orders and settings.auto_manage_positions and alpaca.configured()): return

    risk=await alpaca.risk_status()
    positions=await alpaca.positions()
    if risk.get("blocked") and positions and settings.close_on_daily_guard:
        result=await alpaca.close_all_positions()
        log_event("risk_guard_flatten",None,json.dumps({"risk":risk,"result":result}))
        TRACKED.clear(); return
    if not positions: TRACKED.clear(); return

    symbols=[(p.get("symbol") or "").upper() for p in positions if p.get("symbol")]
    bars_map=await alpaca.intraday_bars(symbols,minutes=180)
    regime=await alpaca.market_regime()
    now=datetime.now(timezone.utc)

    for p in positions:
        symbol=(p.get("symbol") or "").upper()
        if not symbol: continue
        entry=float(p.get("avg_entry_price") or 0); current=float(p.get("current_price") or 0)
        if entry<=0 or current<=0: continue
        rows=bars_map.get(symbol,[]); closes=[float(b.get("c") or 0) for b in rows if float(b.get("c") or 0)>0]
        if len(closes)<20: continue
        ema20=_ema(closes[-80:],20); vwap=_vwap(rows)
        rec=TRACKED.setdefault(symbol,{"first_seen":now.isoformat(),"high":current,"fail_checks":0,"entry":entry})
        rec["high"]=max(float(rec.get("high",current)),current)
        first=datetime.fromisoformat(rec["first_seen"]); held=(now-first).total_seconds()/60

        # Infer initial risk from a conservative 1.5% fallback when broker position lacks stop metadata.
        initial_r=max(entry*0.015,0.01)
        r_now=(current-entry)/initial_r; r_high=(rec["high"]-entry)/initial_r

        thesis_failed=current < ema20 and current < vwap
        rec["fail_checks"] = int(rec.get("fail_checks",0))+1 if thesis_failed else 0

        if rec["fail_checks"] >= settings.thesis_fail_checks:
            await _close(symbol,"thesis_invalidated",{"current":current,"ema20":ema20,"vwap":vwap,"r_now":round(r_now,2)}); continue

        if r_high >= settings.protect_profit_after_r and r_now <= settings.protected_floor_r:
            await _close(symbol,"profit_protection",{"r_high":round(r_high,2),"r_now":round(r_now,2)}); continue

        if not regime.get("longs_allowed",True) and current < entry and r_now <= -0.35:
            await _close(symbol,"market_regime_risk_off",{"r_now":round(r_now,2)}); continue

        if held >= settings.max_hold_minutes and r_now < 0.5:
            await _close(symbol,"time_stop",{"held_minutes":round(held,1),"r_now":round(r_now,2)})


async def manager_loop():
    global LAST_ERROR
    while True:
        try: await manage_once()
        except Exception as e:
            LAST_ERROR=str(e); log_event("trade_manager_error",None,json.dumps({"error":LAST_ERROR}))
        await asyncio.sleep(settings.manager_interval_seconds)
