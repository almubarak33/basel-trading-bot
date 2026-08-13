from __future__ import annotations
import asyncio
import json
from .alpaca import alpaca
from .config import settings
from .db import log_event
from .scanner import scan
from .strategy import position_size

AUTO_ENABLED = settings.auto_paper_trading
STOP_REQUESTED = False
LAST_SCAN = None
LAST_ERROR = None
LAST_CANDIDATE = None


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
        "interval_seconds": settings.scan_interval_seconds,
    }


async def auto_loop():
    global LAST_SCAN, LAST_ERROR, LAST_CANDIDATE
    while not STOP_REQUESTED:
        try:
            if AUTO_ENABLED and settings.paper and alpaca.configured():
                clock = await alpaca.clock()
                if clock.get("is_open", False):
                    rows = await scan()
                    LAST_SCAN = asyncio.get_running_loop().time()
                    eligible = [r for r in rows if r.get("eligible")]
                    LAST_CANDIDATE = eligible[0] if eligible else None
                    log_event("auto_scan", None, json.dumps({"eligible": len(eligible)}))
                    if settings.enable_orders and eligible:
                        await maybe_place_paper_order(eligible[0])
        except Exception as e:
            LAST_ERROR = str(e)
            log_event("auto_error", None, json.dumps({"error": LAST_ERROR}))
        await asyncio.sleep(settings.scan_interval_seconds)


async def maybe_place_paper_order(candidate: dict):
    # Paper-only experimental execution. Live trading remains blocked in alpaca.py.
    if not settings.paper or not settings.enable_orders:
        return

    symbol = candidate["symbol"].upper()
    positions = await alpaca.positions()
    if len(positions) >= settings.max_open_positions:
        return
    if any((p.get("symbol") or "").upper() == symbol for p in positions):
        return

    account = await alpaca.account()
    equity = float(account.get("equity", settings.paper_equity))
    entry = float(candidate["price"])
    if entry <= 0:
        return

    # v1 test assumptions only: 1.5% stop, 3.0% target (2R).
    stop = round(entry * 0.985, 2)
    target = round(entry * 1.03, 2)
    qty = position_size(equity, entry, stop)
    if qty < 1:
        return

    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": str(round(entry, 2)),
        "order_class": "bracket",
        "take_profit": {"limit_price": str(target)},
        "stop_loss": {"stop_price": str(stop)},
        "client_order_id": f"basel-auto-{symbol.lower()}",
    }
    result = await alpaca.submit_order(payload)
    log_event("auto_paper_order", symbol, json.dumps(result))
