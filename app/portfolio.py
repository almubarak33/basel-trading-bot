from __future__ import annotations
import time
from .alpaca import alpaca
from .trade_ledger import build_round_trips

_LEDGER_CACHE={"at":0.0,"closed":[]}
LEDGER_TTL_SECONDS=45


def _f(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default


def _simulation_payload() -> dict:
    open_positions = [
        {"symbol":"NOVA","qty":420,"avg_entry_price":4.84,"current_price":5.06,"market_value":2125.2,"unrealized_pl":92.4,"unrealized_plpc":0.0455,"side":"long"},
        {"symbol":"KXIN","qty":180,"avg_entry_price":7.17,"current_price":7.09,"market_value":1276.2,"unrealized_pl":-14.4,"unrealized_plpc":-0.0112,"side":"long"},
    ]
    closed = [
        {"symbol":"PLAG","qty":300,"entry":1.03,"exit":1.41,"pnl":114.0,"pnl_pct":36.89,"reason":"target","source":"simulation","closed_at":"2026-08-14T17:11:00+00:00"},
        {"symbol":"SPAI","qty":120,"entry":6.12,"exit":6.74,"pnl":74.4,"pnl_pct":10.13,"reason":"manager_exit","source":"simulation","closed_at":"2026-08-14T16:22:00+00:00"},
        {"symbol":"BOLT","qty":90,"entry":12.92,"exit":12.63,"pnl":-26.1,"pnl_pct":-2.24,"reason":"stop","source":"simulation","closed_at":"2026-08-14T15:54:00+00:00"},
        {"symbol":"AERO","qty":250,"entry":3.47,"exit":3.71,"pnl":60.0,"pnl_pct":6.92,"reason":"time_exit","source":"simulation","closed_at":"2026-08-14T15:05:00+00:00"},
    ]
    return summarize(open_positions, closed, equity=20000.0, day_pnl=300.3)


def summarize(open_positions:list[dict], closed:list[dict], equity:float, day_pnl:float|None=None) -> dict:
    op=[]; total_exposure=0.0; open_pnl=0.0
    for p in open_positions or []:
        mv=abs(_f(p.get("market_value"))); upl=_f(p.get("unrealized_pl")); uplpc=_f(p.get("unrealized_plpc"))*100
        total_exposure += mv; open_pnl += upl
        op.append({"symbol":(p.get("symbol") or "").upper(),"qty":abs(_f(p.get("qty"))),"side":p.get("side") or "long",
            "entry":_f(p.get("avg_entry_price")),"current":_f(p.get("current_price")),"market_value":round(mv,2),
            "pnl":round(upl,2),"pnl_pct":round(uplpc,2),"change_today_pct":round(_f(p.get("change_today"))*100,2)})
    wins=[x for x in closed if _f(x.get("pnl"))>0]; losses=[x for x in closed if _f(x.get("pnl"))<0]
    realized=sum(_f(x.get("pnl")) for x in closed)
    if day_pnl is None: day_pnl=realized+open_pnl
    closed_count=len(closed); win_rate=(len(wins)/closed_count*100) if closed_count else 0.0; loss_rate=(len(losses)/closed_count*100) if closed_count else 0.0
    best=max(closed,key=lambda x:_f(x.get("pnl")),default=None); worst=min(closed,key=lambda x:_f(x.get("pnl")),default=None)
    gross_win=sum(_f(x.get("pnl")) for x in wins); gross_loss=abs(sum(_f(x.get("pnl")) for x in losses))
    avg_win=(gross_win/len(wins)) if wins else 0.0; avg_loss=(-gross_loss/len(losses)) if losses else 0.0
    return {"summary":{
            "equity":round(equity,2),"day_pnl":round(day_pnl,2),"day_pnl_pct":round((day_pnl/equity*100) if equity else 0,2),
            "open_positions":len(op),"closed_trades":closed_count,"wins":len(wins),"losses":len(losses),
            "win_rate_pct":round(win_rate,1),"loss_rate_pct":round(loss_rate,1),
            "exposure":round(total_exposure,2),"exposure_pct":round((total_exposure/equity*100) if equity else 0,1),
            "open_pnl":round(open_pnl,2),"realized_pnl":round(realized,2),
            "profit_factor":round((gross_win/gross_loss) if gross_loss else (999.0 if gross_win else 0.0),2),
            "avg_closed_pnl":round((realized/closed_count) if closed_count else 0.0,2),
            "avg_win_pnl":round(avg_win,2),"avg_loss_pnl":round(avg_loss,2),
            "best_trade":best,"worst_trade":worst},
        "open":op,"closed":closed,
        "note":"Closed trades are reconstructed from Alpaca FILL activities; partial exits are grouped into one round trip."}


async def _closed_ledger() -> list[dict]:
    now=time.monotonic()
    if _LEDGER_CACHE["closed"] and now-_LEDGER_CACHE["at"] < LEDGER_TTL_SECONDS:
        return _LEDGER_CACHE["closed"]
    fills=await alpaca.fill_activities(days=90,max_pages=10)
    closed=build_round_trips(fills)[:100]
    _LEDGER_CACHE.update({"at":now,"closed":closed})
    return closed


async def dashboard_portfolio(simulation:bool=False) -> dict:
    if simulation: return _simulation_payload()
    account=await alpaca.account(); positions=await alpaca.positions()
    equity=_f(account.get("equity")); last=_f(account.get("last_equity"),equity); day_pnl=equity-last
    return summarize(positions,await _closed_ledger(),equity,day_pnl)
