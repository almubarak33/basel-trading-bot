from __future__ import annotations
import asyncio
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import auth
from .alpaca import alpaca
from .config import settings
from .chart_data import completed_session_closes
from .db import init_db, log_event, recent_events
from .scanner import scan
from .strategy import position_size
from .session import NY
from . import engine, simulation, trade_manager
from .orders import build_runner_order
from .optionalpha import trigger_webhook
from .intelligence import enrich_candidate, market_brief
from .messages import DEFAULT_LANGUAGE, LANGUAGES, MESSAGES
from .portfolio import dashboard_portfolio

app = FastAPI(title="Basel Trader Mobile", version="1.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")
KILL_SWITCH = False
protected = [Depends(auth.require_auth)]


def scanner_profile() -> dict:
    return {
        "profile":settings.trading_profile,"price_min":settings.min_price,
        "price_max":settings.max_price if settings.max_price>0 else None,
        "change_min_pct":settings.min_change_pct,
        "execution_change_min_pct":settings.min_execution_change_pct,
        "change_max_pct":settings.max_change_pct if settings.max_change_pct>0 else None,
        "min_score":settings.min_score,"min_intel_score":settings.min_intel_score,
        "min_rvol":settings.min_rvol,"universe_limit":settings.screener_universe_limit,
        "movers_top":settings.movers_top,"actives_top":settings.actives_top,
        "extended_hours":settings.scan_extended_hours,
    }

class OrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float | None = Field(default=None, gt=0)

class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)

@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(engine.auto_loop())
    asyncio.create_task(trade_manager.manager_loop())

@app.get("/", response_class=HTMLResponse)
def home(): return (Path(__file__).resolve().parent / "static" / "index.html").read_text()

@app.get("/api/status", dependencies=protected)
async def status():
    if not alpaca.configured():
        sim = simulation.status()
        sim.update({"orders_enabled":False,"option_alpha_configured":bool(settings.option_alpha_webhook_url),
            "option_alpha_enabled":settings.option_alpha_enabled,"kill_switch":KILL_SWITCH,
            "risk_per_trade_pct":settings.risk_per_trade*100,"max_daily_loss_pct":settings.max_daily_loss*100,
            "min_score":settings.min_score,"min_rvol":settings.min_rvol,"opening_delay_minutes":settings.opening_delay_minutes,
            "engine":engine.state(),"trade_manager":trade_manager.state(),
            "risk_status":{"blocked":False,"drawdown_pct":0.0,"simulation":True},
            "scanner_profile":scanner_profile()})
        return sim
    base={"mode":"PAPER" if settings.paper else "BLOCKED","orders_enabled":settings.enable_orders,"configured":True,
        "option_alpha_configured":bool(settings.option_alpha_webhook_url),"option_alpha_enabled":settings.option_alpha_enabled,
        "kill_switch":KILL_SWITCH,"risk_per_trade_pct":settings.risk_per_trade*100,
        "max_daily_loss_pct":settings.max_daily_loss*100,"min_score":settings.min_score,"min_rvol":settings.min_rvol,
        "opening_delay_minutes":settings.opening_delay_minutes,"engine":engine.state(),"trade_manager":trade_manager.state(),
        "scanner_profile":scanner_profile()}
    try:
        account=await alpaca.account(); clock=await alpaca.clock(); risk=await alpaca.risk_status(); regime=await alpaca.market_regime()
        base.update({"equity":float(account.get("equity",0)),"buying_power":float(account.get("buying_power",0)),
            "market_open":bool(clock.get("is_open",False)),"next_open":clock.get("next_open"),"next_close":clock.get("next_close"),
            "risk_status":risk,"market_regime":regime})
    except Exception as e: base["broker_error"]=str(e)
    return base

@app.get("/api/pro/dashboard", dependencies=protected)
async def pro_dashboard():
    s=await status(); is_sim=not alpaca.configured()
    try:
        rows=simulation.scan() if is_sim else await scan()
        enriched=[enrich_candidate(r) for r in rows]
        enriched.sort(key=lambda r:(r.get("decision",{}).get("action")=="ARM",r.get("intel_score",0)),reverse=True)
        portfolio=await dashboard_portfolio(simulation=is_sim)
        actions=Counter((r.get("decision") or {}).get("action","UNKNOWN") for r in enriched)
        rejects=Counter(item.get("code","unknown") for r in enriched for item in (r.get("reject_codes") or []))
        diagnostics={"discovered":len(enriched),"actions":dict(actions),
            "top_rejections":dict(rejects.most_common(8)),"profile":scanner_profile()}
        return {"simulation":is_sim,"status":s,"portfolio":portfolio,"market_brief":market_brief(s),
            "radar":enriched,"top_signal":enriched[0] if enriched else None,
            "events":recent_events(30),
            "scanner_diagnostics":diagnostics,
            "modules":{"smart_radar":True,"smart_map":True,"risk_engine":True,"market_regime":True,
                "catalyst_feed":True,"microstructure":True,"strategy_selector":True,"insider_sec":False,
                "paper_execution":alpaca.configured(),"autonomous_entry":True,"autonomous_exit":True}}
    except Exception as e: raise HTTPException(502,f"Pro dashboard error: {e}")

@app.get("/api/stock/{symbol}", dependencies=protected)
async def stock_detail(symbol: str):
    symbol=symbol.upper().strip()
    if not symbol or len(symbol)>10: raise HTTPException(400,"رمز السهم غير صالح")
    is_sim=not alpaca.configured()
    try:
        if is_sim:
            rows=[enrich_candidate(r) for r in simulation.scan()]
            row=next((r for r in rows if r.get("symbol","").upper()==symbol),None)
            if row is None: raise HTTPException(404,"السهم غير موجود في المحاكاة")
            base=float(row.get("price") or 1)
            bars=[]; daily=[]
            session_day=datetime.now(NY).replace(hour=9,minute=30,second=0,microsecond=0)
            days=[]
            while len(days)<5:
                if session_day.weekday()<5: days.append(session_day)
                session_day-=timedelta(days=1)
            for day_index,session_start in enumerate(reversed(days)):
                day_bars=[]
                for i in range(78):
                    wave=math.sin((i+day_index*5)/7)*0.012 + math.sin(i/17)*0.008
                    trend=(i-45)*0.0007 + (day_index-4)*0.004
                    close=base*(1+wave+trend)
                    open_=close*(1-0.003*math.sin(i))
                    high=max(open_,close)*1.004; low=min(open_,close)*0.996
                    bar={"t":(session_start+timedelta(minutes=i*5)).isoformat(),
                         "o":round(open_,4),"h":round(high,4),"l":round(low,4),"c":round(close,4),
                         "v":int(25000+15000*abs(math.sin(i/5)))}
                    bars.append(bar); day_bars.append(bar)
                daily.append({"t":session_start.isoformat(),"c":day_bars[-1]["c"]})
            return {"simulation":True,"symbol":symbol,"candidate":row,"bars":bars,
                    "previous_closes":completed_session_closes(daily),"news":[],"position":None}

        rows=await scan()
        enriched=[enrich_candidate(r) for r in rows]
        row=next((r for r in enriched if r.get("symbol","").upper()==symbol),None)
        bars_map=await alpaca.intraday_bars([symbol],minutes=8*24*60)
        daily_map=await alpaca.daily_bars([symbol],days=15)
        news_map=await alpaca.news([symbol],hours=48,limit=20)
        position=None
        try: position=await alpaca.position(symbol)
        except Exception: pass
        return {"simulation":False,"symbol":symbol,"candidate":row,"bars":bars_map.get(symbol,[]),
                "previous_closes":completed_session_closes(daily_map.get(symbol,[])),
                "news":news_map.get(symbol,[])[:10],"position":position}
    except HTTPException: raise
    except Exception as e: raise HTTPException(502,f"تعذر تحميل بيانات السهم: {e}")

@app.get("/api/portfolio", dependencies=protected)
async def portfolio(): return await dashboard_portfolio(simulation=not alpaca.configured())

@app.get("/api/i18n")
def i18n(): return {"languages":list(LANGUAGES),"default":DEFAULT_LANGUAGE,"messages":MESSAGES}

@app.get("/api/session")
def session_state(basel_session: str|None=Cookie(default=None)):
    return {"authenticated":auth.is_valid_session(basel_session),"ephemeral_token":auth.TOKEN_IS_EPHEMERAL}

@app.post("/api/login")
def login(req:LoginRequest,request:Request,response:Response):
    remaining=auth.throttle_state(request)
    if remaining>0: raise HTTPException(429,f"محاولات كثيرة. حاول بعد {int(remaining)} ثانية")
    if not auth.token_matches(req.token):
        auth.register_failure(request); raise HTTPException(401,"رمز الدخول غير صحيح")
    auth.clear_failures(request); auth.set_session_cookie(response,request,auth.create_session())
    log_event("login",None,json.dumps({"ok":True})); return {"authenticated":True}

@app.post("/api/logout")
def logout(response:Response,basel_session:str|None=Cookie(default=None)):
    auth.destroy_session(basel_session); auth.clear_session_cookie(response); return {"authenticated":False}

@app.get("/api/trade-manager",dependencies=protected)
def trade_manager_status(): return trade_manager.state()

@app.get("/api/risk-status",dependencies=protected)
async def risk_status():
    if not alpaca.configured(): return {"blocked":False,"drawdown_pct":0.0,"simulation":True}
    return await alpaca.risk_status()

@app.get("/api/scan",dependencies=protected)
async def api_scan():
    try:
        if not alpaca.configured():
            rows=simulation.scan(); log_event("simulation_scan",None,json.dumps({"count":len(rows)})); return {"candidates":rows,"simulation":True}
        rows=await scan(); log_event("scan",None,json.dumps({"count":len(rows)})); return {"candidates":rows,"simulation":False}
    except Exception as e: raise HTTPException(502,f"خطأ في بيانات السوق: {e}")

@app.get("/api/trades",dependencies=protected)
def trades(): return {"events":recent_events()}

@app.post("/api/optionalpha/test",dependencies=protected)
async def optionalpha_test():
    if KILL_SWITCH: raise HTTPException(423,"مفتاح الإيقاف مفعّل")
    try:
        result=await trigger_webhook(); log_event("optionalpha_webhook",None,json.dumps(result)); return result
    except Exception as e: raise HTTPException(502,f"خطأ Option Alpha: {e}")

@app.post("/api/auto",dependencies=protected)
def auto(enabled:bool):
    if enabled and (not settings.paper or not alpaca.configured()): raise HTTPException(403,"التداول الآلي يتطلب حساب Alpaca Paper مربوط")
    if enabled and KILL_SWITCH: raise HTTPException(423,"مفتاح الإيقاف مفعّل")
    return {"auto_enabled":engine.set_auto(enabled)}

@app.post("/api/kill-switch",dependencies=protected)
async def kill_switch(enabled:bool=True):
    global KILL_SWITCH; KILL_SWITCH=enabled
    if enabled:
        engine.set_auto(False)
        if alpaca.configured() and settings.paper and settings.enable_orders:
            try:
                positions=await alpaca.positions(); result=await alpaca.close_all_positions()
                log_event("kill_switch_flatten",None,json.dumps({"positions":positions,"result":result}))
            except Exception as e: log_event("kill_switch_flatten_error",None,json.dumps({"error":str(e)}))
    log_event("kill_switch",None,json.dumps({"enabled":enabled})); return {"kill_switch":KILL_SWITCH}

@app.post("/api/paper/order",dependencies=protected)
async def paper_order(req:OrderRequest):
    if not alpaca.configured(): raise HTTPException(403,"وضع محاكاة فقط. اربط Alpaca Paper لإرسال الأوامر")
    if KILL_SWITCH: raise HTTPException(423,"مفتاح الإيقاف مفعّل")
    if not settings.paper: raise HTTPException(403,"التداول الحقيقي معطل")
    if not settings.enable_orders: raise HTTPException(403,"أوامر Paper معطلة")
    risk=await alpaca.risk_status()
    if risk.get("blocked"): raise HTTPException(423,"تم بلوغ حد الخسارة اليومية")
    if req.stop>=req.entry: raise HTTPException(400,"وقف الخسارة يجب أن يكون تحت الدخول")
    account=await alpaca.account(); positions=await alpaca.positions()
    if len(positions)>=settings.max_open_positions: raise HTTPException(409,"تم بلوغ الحد الأقصى للصفقات المفتوحة")
    equity=float(account.get("equity",settings.paper_equity)); qty=position_size(equity,req.entry,req.stop)
    if qty<1: raise HTTPException(400,"حجم الصفقة المحسوب صفر")
    payload=build_runner_order(req.symbol,qty,req.entry,req.stop,source="manual")
    result=await alpaca.submit_order(payload)
    log_event("paper_order",req.symbol.upper(),json.dumps({
        "result":result,"runner_mode":True,"target_reference":req.target,
    }))
    return {"qty":qty,"order":result,"runner_mode":True,"target_reference":req.target}
