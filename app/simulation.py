from __future__ import annotations
import random
from copy import deepcopy

from .messages import render

def _codes(*names: str) -> list[dict]:
    return [{"code": name} for name in names]


_BASE = [
    {"symbol":"NOVA","price":4.82,"change_pct":18.4,"rvol":5.4,"spread_pct":0.18,"score":92,"vwap":4.74,"ema9":4.78,"ema20":4.70,"atr":0.11,"entry":4.84,"stop":4.68,"target":5.16,"risk_pct":3.31,"eligible":True,"setup":"PULLBACK_RECLAIM","reason_codes":_codes("pullback_detected","reclaim_confirmed","volume_confirmed"),"reject_codes":[]},
    {"symbol":"KXIN","price":7.15,"change_pct":12.6,"rvol":3.9,"spread_pct":0.21,"score":88,"vwap":7.05,"ema9":7.10,"ema20":7.01,"atr":0.16,"entry":7.17,"stop":6.94,"target":7.63,"risk_pct":3.21,"eligible":True,"setup":"PULLBACK_RECLAIM","reason_codes":_codes("pullback_detected","reclaim_confirmed","volume_confirmed"),"reject_codes":[]},
    {"symbol":"PICO","price":0.74,"change_pct":6.8,"rvol":4.6,"spread_pct":0.72,"score":82,"vwap":0.72,"ema9":0.735,"ema20":0.71,"atr":0.03,"entry":0.7412,"stop":0.7041,"target":0.8154,"risk_pct":5.01,"eligible":True,"setup":"MOMENTUM_BREAKOUT","reason_codes":_codes("momentum_breakout","volume_confirmed"),"reject_codes":[]},
    {"symbol":"ALTA","price":142.60,"change_pct":4.9,"rvol":2.4,"spread_pct":0.08,"score":79,"vwap":140.80,"ema9":141.90,"ema20":140.40,"atr":2.10,"entry":142.60,"stop":139.80,"target":148.20,"risk_pct":1.96,"eligible":True,"setup":"MOMENTUM_BREAKOUT","reason_codes":_codes("momentum_breakout","volume_confirmed"),"reject_codes":[]},
    {"symbol":"AERO","price":3.46,"change_pct":27.8,"rvol":6.7,"spread_pct":0.33,"score":81,"vwap":3.31,"ema9":3.40,"ema20":3.28,"atr":0.14,"entry":3.47,"stop":3.31,"target":3.79,"risk_pct":4.61,"eligible":False,"setup":"WAIT","reason_codes":_codes("volume_confirmed"),"reject_codes":_codes("vwap_extended","no_pullback")},
    {"symbol":"BOLT","price":12.90,"change_pct":6.4,"rvol":1.8,"spread_pct":0.62,"score":74,"vwap":12.71,"ema9":12.78,"ema20":12.69,"atr":0.22,"entry":12.92,"stop":12.60,"target":13.56,"risk_pct":2.48,"eligible":False,"setup":"WAIT","reason_codes":[],"reject_codes":_codes("rvol_too_low","spread_too_wide","no_reclaim")}
]

_state = deepcopy(_BASE)

def status():
    return {
        "mode":"SIMULATION",
        "configured":False,
        "market_open":True,
        "equity":20000.0,
        "buying_power":40000.0,
        "daily_drawdown_pct":0.0,
        "daily_loss_guard":False,
        "simulation":True,
        "market_regime":{"longs_allowed":True,"healthy_indexes":2,"details":{"SPY":{"healthy":True,"ret15_pct":0.18},"QQQ":{"healthy":True,"ret15_pct":0.24}}}
    }

def scan():
    global _state
    rows=[]
    for item in _state:
        x=deepcopy(item)
        x["price"]=round(max(0.5, x["price"]*(1+random.uniform(-0.004,0.006))),2)
        x["score"]=max(60,min(99,int(x["score"]+random.randint(-2,2))))
        x["vwap_extension_pct"]=round((x["price"]/x["vwap"]-1)*100,2)
        x["one_bar_move_pct"]=round(random.uniform(0.1,1.8),2)
        x["pullback_seen"]=x.get("setup")=="PULLBACK_RECLAIM"
        x["breakout_confirmed"]=x.get("setup")=="MOMENTUM_BREAKOUT"
        x["reclaim_confirmed"]=x["eligible"]
        x["volume_confirmed"]=x["rvol"]>=2.0
        x["market_regime"]=status()["market_regime"]
        x["reasons"]=[render(c["code"],c.get("params")) for c in x["reason_codes"]]
        x["reject_reasons"]=[render(c["code"],c.get("params")) for c in x["reject_codes"]]
        rows.append(x)
    _state=rows
    return sorted(rows,key=lambda r:(r["eligible"],r["score"],r["rvol"]),reverse=True)
