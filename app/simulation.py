from __future__ import annotations
import random
from copy import deepcopy

_BASE = [
    {"symbol":"NOVA","price":4.82,"change_pct":18.4,"rvol":5.4,"spread_pct":0.18,"score":92,"vwap":4.74,"ema9":4.78,"ema20":4.70,"atr":0.11,"entry":4.84,"stop":4.68,"target":5.16,"risk_pct":3.31,"eligible":True,"setup":"PULLBACK_RECLAIM","reasons":["Controlled pullback detected","VWAP + EMA reclaim confirmed","Reclaim volume confirmed"],"reject_reasons":[]},
    {"symbol":"KXIN","price":7.15,"change_pct":12.6,"rvol":3.9,"spread_pct":0.21,"score":88,"vwap":7.05,"ema9":7.10,"ema20":7.01,"atr":0.16,"entry":7.17,"stop":6.94,"target":7.63,"risk_pct":3.21,"eligible":True,"setup":"PULLBACK_RECLAIM","reasons":["Controlled pullback detected","VWAP + EMA reclaim confirmed","Reclaim volume confirmed"],"reject_reasons":[]},
    {"symbol":"AERO","price":3.46,"change_pct":27.8,"rvol":6.7,"spread_pct":0.33,"score":81,"vwap":3.31,"ema9":3.40,"ema20":3.28,"atr":0.14,"entry":3.47,"stop":3.31,"target":3.79,"risk_pct":4.61,"eligible":False,"setup":"WAIT","reasons":["Reclaim volume confirmed"],"reject_reasons":["FOMO block: too far above VWAP","No controlled pullback yet"]},
    {"symbol":"BOLT","price":12.90,"change_pct":6.4,"rvol":1.8,"spread_pct":0.62,"score":74,"vwap":12.71,"ema9":12.78,"ema20":12.69,"atr":0.22,"entry":12.92,"stop":12.60,"target":13.56,"risk_pct":2.48,"eligible":False,"setup":"WAIT","reasons":[],"reject_reasons":["RVOL below threshold","Spread too wide","No VWAP/EMA reclaim confirmation"]}
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
        x["pullback_seen"]=x["eligible"]
        x["reclaim_confirmed"]=x["eligible"]
        x["volume_confirmed"]=x["rvol"]>=2.0
        x["market_regime"]=status()["market_regime"]
        rows.append(x)
    _state=rows
    return sorted(rows,key=lambda r:(r["eligible"],r["score"],r["rvol"]),reverse=True)
