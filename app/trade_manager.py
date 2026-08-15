from __future__ import annotations
import asyncio, json
from datetime import datetime, timezone
from .alpaca import alpaca, extract_stop_prices
from .config import settings
from .db import log_event
from .exits import PositionState, evaluate_exit
from .orders import build_extended_hours_exit
from .session import NY, minutes_until_day_end, tradeable_now
from . import soft_stops

TRACKED: dict[str, PositionState] = {}
LAST_RUN = None
LAST_ERROR = None
LAST_ACTION = None


def state():
    tracked={s:{"entry":p.entry,"high":p.high,"fail_checks":p.fail_checks,"first_seen":p.first_seen.isoformat()} for s,p in TRACKED.items()}
    return {"enabled": settings.auto_manage_positions,"last_run":LAST_RUN,"last_error":LAST_ERROR,
        "last_action":LAST_ACTION,"tracked":tracked,"soft_stops":soft_stops.snapshot()}


def _qty(position: dict) -> int:
    try: return abs(int(float(position.get("qty") or 0)))
    except (TypeError, ValueError): return 0


async def _sell(symbol: str, position: dict, price: float, extended: bool):
    """Exit one position by whichever route the current session allows."""
    if not extended:
        return await alpaca.close_position(symbol)
    # لا أوامر سوق ولا إغلاق مركز مباشر خارج الجلسة الرسمية — البيع أمر limit.
    qty=_qty(position)
    if qty<1 or price<=0: raise RuntimeError(f"cannot price an extended-hours exit for {symbol}")
    return await alpaca.submit_order(build_extended_hours_exit(symbol,qty,price))


async def _close(symbol, reason, meta=None, extended=False, position=None, price=0.0):
    global LAST_ACTION
    if position is None:
        try: position=await alpaca.position(symbol)
        except Exception: position={}
    result=await _sell(symbol,position,price or float(position.get("current_price") or 0),extended)
    LAST_ACTION={"symbol":symbol,"action":"CLOSE","reason":reason,"ts":datetime.now(timezone.utc).isoformat()}
    payload={"reason":reason,"result":result,"position":position,"extended_hours":extended}
    if meta: payload.update(meta)
    log_event("auto_exit",symbol,json.dumps(payload))
    TRACKED.pop(symbol,None); soft_stops.forget(symbol)


async def _flatten(positions, event, meta, extended):
    """Close everything. In the extended session that means one limit order each."""
    if extended:
        orders=[]
        for p in positions:
            symbol=(p.get("symbol") or "").upper()
            if not symbol: continue
            try: orders.append(await _sell(symbol,p,float(p.get("current_price") or 0),True))
            except Exception as e: orders.append({"symbol":symbol,"error":str(e)})
        result={"extended_hours":True,"orders":orders}
    else:
        result=await alpaca.close_all_positions()
    log_event(event,None,json.dumps({**meta,"result":result}))
    TRACKED.clear(); soft_stops.clear()


async def manage_once(now: datetime | None = None):
    global LAST_RUN, LAST_ERROR
    LAST_RUN=datetime.now(timezone.utc).isoformat(); LAST_ERROR=None
    if not (settings.paper and settings.enable_orders and settings.auto_manage_positions and alpaca.configured()): return

    now=now or datetime.now(timezone.utc)
    clock=await alpaca.clock()
    market_open=bool(clock.get("is_open",False))
    if not tradeable_now(now.astimezone(NY),market_open,settings.trade_after_hours,settings.trade_pre_market):
        TRACKED.clear(); return
    # الوسيط لا يقبل أمر سوق خارج 09:30–16:00، فكل مخرج هنا يصبح limit.
    extended=not market_open

    risk=await alpaca.risk_status()
    positions=await alpaca.positions()
    if risk.get("blocked") and positions and settings.close_on_daily_guard:
        await _flatten(positions,"risk_guard_flatten",{"risk":risk,"positions":positions},extended); return
    if not positions: TRACKED.clear(); soft_stops.clear(); return

    minutes_left=minutes_until_day_end(clock.get("next_close"),settings.trade_after_hours,now)
    if settings.eod_flatten_enabled and minutes_left is not None and 0<minutes_left<=settings.eod_flatten_minutes:
        await _flatten(positions,"eod_flatten",{
            "minutes_to_close":round(minutes_left,1),
            "symbols":[(p.get("symbol") or "").upper() for p in positions],
            "positions":positions,
        },extended); return

    symbols=[(p.get("symbol") or "").upper() for p in positions if p.get("symbol")]
    soft_stops.retain_only(symbols)
    bars_map=await alpaca.intraday_bars(symbols,minutes=180)
    regime=await alpaca.market_regime()
    stops=extract_stop_prices(await alpaca.open_orders())

    for p in positions:
        symbol=(p.get("symbol") or "").upper()
        if not symbol: continue
        entry=float(p.get("avg_entry_price") or 0); current=float(p.get("current_price") or 0)
        if entry<=0 or current<=0: continue
        rec=TRACKED.get(symbol)
        if rec is None:
            rec=PositionState(symbol=symbol,entry=entry,first_seen=now,high=current)
            TRACKED[symbol]=rec
        # الوقف عند الوسيط أمر يومي ينتهي عند الجرس. نحفظه ما دام قائماً لنطبّقه
        # بأنفسنا بعد ذلك، وإلا بقي المركز بلا حماية في الجلسة الممتدة.
        broker_stop=stops.get(symbol,0.0)
        if broker_stop>0: soft_stops.remember(symbol,broker_stop)
        protective=broker_stop or soft_stops.get(symbol)
        if rec.initial_risk_per_share is None and 0<protective<rec.entry:
            rec.initial_risk_per_share=rec.entry-protective
        if broker_stop<=0 and 0<protective and current<=protective:
            await _close(symbol,"soft_stop_hit",{"stop":protective,"current":current},
                         extended=extended,position=p,price=current)
            continue
        decision=evaluate_exit(rec,current,bars_map.get(symbol,[]),regime,now,settings)
        if decision:
            await _close(symbol,decision.reason,decision.meta,extended=extended,position=p,price=current)


async def manager_loop():
    global LAST_ERROR
    while True:
        try: await manage_once()
        except Exception as e:
            LAST_ERROR=str(e); log_event("trade_manager_error",None,json.dumps({"error":LAST_ERROR}))
        await asyncio.sleep(settings.manager_interval_seconds)
