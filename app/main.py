from __future__ import annotations
import asyncio
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .alpaca import alpaca
from .config import settings
from .db import init_db, log_event, recent_events
from .scanner import scan
from .strategy import position_size
from . import engine

app = FastAPI(title="Basel Trader Mobile", version="0.3.0")
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")
KILL_SWITCH = False

class OrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)

@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(engine.auto_loop())

@app.get("/", response_class=HTMLResponse)
def home():
    return (Path(__file__).resolve().parent / "static" / "index.html").read_text()

@app.get("/api/status")
async def status():
    base = {
        "mode": "PAPER" if settings.paper else "BLOCKED",
        "orders_enabled": settings.enable_orders,
        "configured": alpaca.configured(),
        "kill_switch": KILL_SWITCH,
        "risk_per_trade_pct": settings.risk_per_trade * 100,
        "max_daily_loss_pct": settings.max_daily_loss * 100,
        "min_score": settings.min_score,
        "engine": engine.state(),
    }
    if not alpaca.configured():
        return base
    try:
        account = await alpaca.account()
        clock = await alpaca.clock()
        base.update({
            "equity": float(account.get("equity", 0)),
            "buying_power": float(account.get("buying_power", 0)),
            "market_open": bool(clock.get("is_open", False)),
            "next_open": clock.get("next_open"),
            "next_close": clock.get("next_close"),
        })
    except Exception as e:
        base["broker_error"] = str(e)
    return base

@app.get("/api/scan")
async def api_scan():
    if not alpaca.configured():
        raise HTTPException(400, "Add Alpaca PAPER API keys first.")
    try:
        rows = await scan()
        log_event("scan", None, json.dumps({"count": len(rows)}))
        return {"candidates": rows}
    except Exception as e:
        raise HTTPException(502, f"Market data error: {e}")

@app.get("/api/trades")
def trades():
    return {"events": recent_events()}

@app.post("/api/auto")
def auto(enabled: bool):
    if enabled and (not settings.paper or not alpaca.configured()):
        raise HTTPException(403, "Auto mode requires a configured Alpaca PAPER account.")
    if enabled and KILL_SWITCH:
        raise HTTPException(423, "Kill switch is ON.")
    return {"auto_enabled": engine.set_auto(enabled)}

@app.post("/api/kill-switch")
def kill_switch(enabled: bool = True):
    global KILL_SWITCH
    KILL_SWITCH = enabled
    if enabled:
        engine.set_auto(False)
    log_event("kill_switch", None, json.dumps({"enabled": enabled}))
    return {"kill_switch": KILL_SWITCH}

@app.post("/api/paper/order")
async def paper_order(req: OrderRequest):
    if KILL_SWITCH:
        raise HTTPException(423, "Kill switch is ON.")
    if not settings.paper:
        raise HTTPException(403, "Live trading is disabled.")
    if not settings.enable_orders:
        raise HTTPException(403, "Paper orders are disabled.")
    if req.stop >= req.entry:
        raise HTTPException(400, "Stop must be below entry for long trades.")
    if req.target <= req.entry:
        raise HTTPException(400, "Target must be above entry.")
    account = await alpaca.account()
    positions = await alpaca.positions()
    if len(positions) >= settings.max_open_positions:
        raise HTTPException(409, "Maximum open positions reached.")
    equity = float(account.get("equity", settings.paper_equity))
    qty = position_size(equity, req.entry, req.stop)
    if qty < 1:
        raise HTTPException(400, "Calculated position size is zero.")
    payload = {
        "symbol": req.symbol.upper(),
        "qty": str(qty),
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": str(round(req.entry, 2)),
        "order_class": "bracket",
        "take_profit": {"limit_price": str(round(req.target, 2))},
        "stop_loss": {"stop_price": str(round(req.stop, 2))},
        "client_order_id": f"basel-{req.symbol.lower()}",
    }
    result = await alpaca.submit_order(payload)
    log_event("paper_order", req.symbol.upper(), json.dumps(result))
    return {"qty": qty, "order": result}
