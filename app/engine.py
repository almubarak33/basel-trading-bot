from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone, timedelta
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
ARMED: dict[str, dict] = {}
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
        "interval_seconds": settings.scan_interval_seconds,
        "armed_symbols": list(ARMED.keys()),
        "cooldown_symbols": list(COOLDOWNS.keys()),
        "entry_model": "PULLBACK_RECLAIM_2_STAGE",
    }


def _cooldown_active(symbol: str) -> bool:
    until = COOLDOWNS.get(symbol)
    if not until:
        return False
    if datetime.now(timezone.utc) >= until:
        COOLDOWNS.pop(symbol, None)
        return False
    return True


def _arm_or_confirm(candidate: dict) -> bool:
    """Require the setup to survive two consecutive scans before execution."""
    symbol = candidate["symbol"].upper()
    current = ARMED.get(symbol)

    if current is None:
        ARMED[symbol] = {
            "count": 1,
            "first_price": float(candidate["price"]),
            "first_score": float(candidate["score"]),
        }
        log_event("setup_armed", symbol, json.dumps(ARMED[symbol]))
        return False

    first_price = float(current.get("first_price", candidate["price"]))
    now_price = float(candidate["price"])
    # Do not confirm if price ran away while waiting; this is deliberate anti-FOMO behavior.
    if first_price > 0 and (now_price / first_price - 1) * 100 > 1.0:
        ARMED.pop(symbol, None)
        log_event("setup_disarmed", symbol, json.dumps({"reason": "price_ran_away"}))
        return False

    current["count"] = int(current.get("count", 1)) + 1
    current["latest_score"] = float(candidate["score"])
    if current["count"] >= 2:
        ARMED.pop(symbol, None)
        return True
    return False


async def auto_loop():
    global LAST_SCAN, LAST_ERROR, LAST_CANDIDATE
    while not STOP_REQUESTED:
        try:
            if AUTO_ENABLED and settings.paper and alpaca.configured():
                clock = await alpaca.clock()
                if clock.get("is_open", False):
                    rows = await scan()
                    LAST_SCAN = datetime.now(timezone.utc).isoformat()
                    eligible = [r for r in rows if r.get("eligible")]
                    LAST_CANDIDATE = eligible[0] if eligible else None
                    log_event("auto_scan", None, json.dumps({"eligible": len(eligible)}))

                    eligible_symbols = {r["symbol"].upper() for r in eligible}
                    # Remove stale armed setups that failed on the next scan.
                    for symbol in list(ARMED.keys()):
                        if symbol not in eligible_symbols:
                            ARMED.pop(symbol, None)
                            log_event("setup_disarmed", symbol, json.dumps({"reason": "setup_failed_recheck"}))

                    if settings.enable_orders:
                        for candidate in eligible[:3]:
                            symbol = candidate["symbol"].upper()
                            if _cooldown_active(symbol):
                                continue
                            if _arm_or_confirm(candidate):
                                await maybe_place_paper_order(candidate)
                                # One new position per scan maximum.
                                break
        except Exception as e:
            LAST_ERROR = str(e)
            log_event("auto_error", None, json.dumps({"error": LAST_ERROR}))
        await asyncio.sleep(settings.scan_interval_seconds)


async def maybe_place_paper_order(candidate: dict):
    # Paper-only. alpaca.py independently blocks live submission.
    if not settings.paper or not settings.enable_orders:
        return

    symbol = candidate["symbol"].upper()
    if _cooldown_active(symbol):
        return

    positions = await alpaca.positions()
    if len(positions) >= settings.max_open_positions:
        return
    if any((p.get("symbol") or "").upper() == symbol for p in positions):
        return

    entry = float(candidate.get("entry") or 0)
    stop = float(candidate.get("stop") or 0)
    target = float(candidate.get("target") or 0)
    if not (target > entry > stop > 0):
        log_event("order_blocked", symbol, json.dumps({"reason": "invalid_structural_levels"}))
        return

    risk_pct = ((entry - stop) / entry) * 100
    if risk_pct > settings.max_stop_pct:
        log_event("order_blocked", symbol, json.dumps({"reason": "stop_too_wide", "risk_pct": risk_pct}))
        return

    account = await alpaca.account()
    equity = float(account.get("equity", settings.paper_equity))
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
        "take_profit": {"limit_price": str(round(target, 2))},
        "stop_loss": {"stop_price": str(round(stop, 2))},
        "client_order_id": f"basel-smart-{symbol.lower()}",
    }

    result = await alpaca.submit_order(payload)
    COOLDOWNS[symbol] = datetime.now(timezone.utc) + timedelta(minutes=settings.symbol_cooldown_minutes)
    log_event(
        "smart_paper_order",
        symbol,
        json.dumps({
            "order": result,
            "setup": candidate.get("setup"),
            "score": candidate.get("score"),
            "entry": entry,
            "stop": stop,
            "target": target,
            "risk_pct": round(risk_pct, 2),
        }),
    )
