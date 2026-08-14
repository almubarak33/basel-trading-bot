from __future__ import annotations
import asyncio, json
from datetime import datetime, timezone
from .alpaca import alpaca, extract_stop_prices
from .config import settings
from .db import log_event
from .exits import PositionState, evaluate_exit
from .session import minutes_until

TRACKED: dict[str, PositionState] = {}
LAST_RUN = None
LAST_ERROR = None
LAST_ACTION = None


def state():
    tracked={s:{"entry":p.entry,"high":p.high,"fail_checks":p.fail_checks,"first_seen":p.first_seen.isoformat()} for s,p in TRACKED.items()}
    return {"enabled": settings.auto_manage_positions,"last_run":LAST_RUN,"last_error":LAST_ERROR,"last_action":LAST_ACTION,"tracked":tracked}


async def _close(symbol, reason, meta=None):
    global LAST_ACTION
    position={}
    try: position=await alpaca.position(symbol)
    except Exception: position={}
    result=await alpaca.close_position(symbol)
    LAST_ACTION={"symbol":symbol,"action":"CLOSE","reason":reason,"ts":datetime.now(timezone.utc).isoformat()}
    payload={"reason":reason,"result":result,"position":position}
    if meta: payload.update(meta)
    log_event("auto_exit",symbol,json.dumps(payload))
    TRACKED.pop(symbol,None)


async def manage_once():
    global LAST_RUN, LAST_ERROR
    LAST_RUN=datetime.now(timezone.utc).isoformat(); LAST_ERROR=None
    if not (settings.paper and settings.enable_orders and settings.auto_manage_positions and alpaca.configured()): return

    clock=await alpaca.clock()
    if not clock.get("is_open",False):
        TRACKED.clear(); return

    risk=await alpaca.risk_status()
    positions=await alpaca.positions()
    if risk.get("blocked") and positions and settings.close_on_daily_guard:
        result=await alpaca.close_all_positions()
        log_event("risk_guard_flatten",None,json.dumps({"risk":risk,"positions":positions,"result":result}))
        TRACKED.clear(); return
    if not positions: TRACKED.clear(); return

    minutes_left=minutes_until(clock.get("next_close"))
    if settings.eod_flatten_enabled and minutes_left is not None and 0<minutes_left<=settings.eod_flatten_minutes:
        result=await alpaca.close_all_positions()
        log_event("eod_flatten",None,json.dumps({
            "minutes_to_close":round(minutes_left,1),
            "symbols":[(p.get("symbol") or "").upper() for p in positions],
            "positions":positions,
            "result":result,
        }))
        TRACKED.clear(); return

    symbols=[(p.get("symbol") or "").upper() for p in positions if p.get("symbol")]
    bars_map=await alpaca.intraday_bars(symbols,minutes=180)
    regime=await alpaca.market_regime()
    stops=extract_stop_prices(await alpaca.open_orders())
    now=datetime.now(timezone.utc)

    for p in positions:
        symbol=(p.get("symbol") or "").upper()
        if not symbol: continue
        entry=float(p.get("avg_entry_price") or 0); current=float(p.get("current_price") or 0)
        if entry<=0 or current<=0: continue
        rec=TRACKED.get(symbol)
        if rec is None:
            rec=PositionState(symbol=symbol,entry=entry,first_seen=now,high=current)
            TRACKED[symbol]=rec
        if rec.initial_risk_per_share is None:
            stop=stops.get(symbol,0.0)
            if 0<stop<rec.entry: rec.initial_risk_per_share=rec.entry-stop
        decision=evaluate_exit(rec,current,bars_map.get(symbol,[]),regime,now,settings)
        if decision:
            await _close(symbol,decision.reason,decision.meta)


async def manager_loop():
    global LAST_ERROR
    while True:
        try: await manage_once()
        except Exception as e:
            LAST_ERROR=str(e); log_event("trade_manager_error",None,json.dumps({"error":LAST_ERROR}))
        await asyncio.sleep(settings.manager_interval_seconds)
