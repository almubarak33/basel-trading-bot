from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone, timedelta
from .alpaca import alpaca
from .arming import ArmingTracker
from .config import settings
from .db import log_event
from .orders import build_extended_hours_entry, build_runner_order, build_signal_order_id
from .portfolio import closed_trades
from .pretrade import evaluate_pretrade
from .protections import ProtectionTracker, from_ledger
from .scanner import scan
from .session import (NY, extended_scan_active, minutes_until_day_end,
                      opening_delay_active, tradeable_now)
from . import soft_stops
from .strategy import position_size
from .intelligence import enrich_candidate
AUTO_ENABLED = settings.auto_paper_trading
STOP_REQUESTED = False
LAST_SCAN = None
LAST_ERROR = None
LAST_CANDIDATE = None
LAST_RISK_STATUS = None
LAST_SCAN_COUNT = 0
LAST_ACTIONABLE_COUNT = 0
LAST_REJECT_COUNTS: dict[str,int] = {}
LAST_SCAN_SESSION = None
LAST_PREFLIGHT = None
ARMED = ArmingTracker(lambda kind, symbol, payload: log_event(kind, symbol, json.dumps(payload)))
# قواطع الدائرة: الحد اليومي وحده لم يُطلق ولا مرة خلال 44 جلسة اختبار
PROTECTIONS = ProtectionTracker()
COOLDOWNS: dict[str, datetime] = {}
# لماذا لم يدخل المحرك صفقة في آخر دورة. كل بوابة كانت تخرج بصمت، فيبدو
# التوقف والعطل متطابقين من الخارج.
IDLE_REASON = "starting"

def set_auto(enabled: bool):
    global AUTO_ENABLED
    AUTO_ENABLED = bool(enabled)
    log_event("auto_toggle", None, json.dumps({"enabled": AUTO_ENABLED}))
    return AUTO_ENABLED

def state():
    return {"auto_enabled":AUTO_ENABLED,"idle_reason":IDLE_REASON,"last_scan":LAST_SCAN,"last_error":LAST_ERROR,
        "last_candidate":LAST_CANDIDATE,"last_risk_status":LAST_RISK_STATUS,
        "last_scan_count":LAST_SCAN_COUNT,"last_actionable_count":LAST_ACTIONABLE_COUNT,
        "last_reject_counts":LAST_REJECT_COUNTS,"last_scan_session":LAST_SCAN_SESSION,
        "last_preflight":LAST_PREFLIGHT,
        "protection_locks":PROTECTIONS.snapshot(datetime.now(timezone.utc)),
        "interval_seconds":settings.scan_interval_seconds,"armed_symbols":ARMED.symbols(),
        "cooldown_symbols":list(COOLDOWNS.keys()),
        "risk_limits":{"max_gross_exposure_pct":settings.max_gross_exposure_pct*100,
                       "max_portfolio_heat_pct":settings.max_portfolio_heat_pct*100,
                       "max_bar_participation_pct":settings.max_bar_participation_pct*100},
        "entry_model":"POINT_IN_TIME_DATA + 2_STAGE + PORTFOLIO_PREFLIGHT + RUNNER_EXIT"}

def _opening_delay_active() -> bool:
    return opening_delay_active(datetime.now(NY), settings.opening_delay_minutes)

def _entry_window_closed(clock: dict, now: datetime | None = None) -> bool:
    minutes_left=minutes_until_day_end(clock.get("next_close"),settings.trade_after_hours,now)
    return False if minutes_left is None else minutes_left <= settings.no_entry_minutes_before_close

def _session_open(clock: dict, now: datetime | None = None) -> bool:
    """Whether the bot may trade right now, regular or extended session."""
    return tradeable_now(now or datetime.now(NY),bool(clock.get("is_open",False)),
        settings.trade_after_hours,settings.trade_pre_market)

def _cooldown_active(symbol: str) -> bool:
    until=COOLDOWNS.get(symbol)
    if not until:return False
    if datetime.now(timezone.utc)>=until:
        COOLDOWNS.pop(symbol,None); return False
    return True


async def _refresh_candidates(session_name: str) -> tuple[list[dict],list[dict]]:
    global LAST_SCAN,LAST_CANDIDATE,LAST_SCAN_COUNT,LAST_ACTIONABLE_COUNT,LAST_REJECT_COUNTS,LAST_SCAN_SESSION
    raw_rows=await scan(); rows=[enrich_candidate(r) for r in raw_rows]
    LAST_SCAN=datetime.now(timezone.utc).isoformat(); LAST_SCAN_SESSION=session_name
    eligible=[r for r in rows if r.get("eligible") and r.get("decision",{}).get("action")=="ARM"]
    eligible.sort(key=lambda r:(r.get("intel_score",0),r.get("score",0),r.get("rvol",0)),reverse=True)
    LAST_CANDIDATE=eligible[0] if eligible else (rows[0] if rows else None)
    LAST_SCAN_COUNT=len(rows); LAST_ACTIONABLE_COUNT=len(eligible)
    reject_counts: dict[str,int]={}
    for row in rows:
        for item in row.get("reject_codes") or []:
            code=item.get("code") if isinstance(item,dict) else str(item)
            reject_counts[code]=reject_counts.get(code,0)+1
    LAST_REJECT_COUNTS=dict(sorted(reject_counts.items(),key=lambda item:item[1],reverse=True)[:8])
    log_event("auto_scan" if session_name=="REGULAR" else "extended_scan",None,json.dumps({
        "profile":settings.trading_profile,"session":session_name,"discovered":len(rows),
        "actionable":len(eligible),"top_rejects":LAST_REJECT_COUNTS,
    }))
    return rows,eligible

async def auto_loop():
    global LAST_SCAN,LAST_ERROR,LAST_CANDIDATE,LAST_RISK_STATUS,AUTO_ENABLED,IDLE_REASON
    while not STOP_REQUESTED:
        try:
            if not AUTO_ENABLED: IDLE_REASON="auto_disabled"
            elif not settings.paper: IDLE_REASON="live_blocked"
            elif not alpaca.configured(): IDLE_REASON="not_configured"
            if AUTO_ENABLED and settings.paper and alpaca.configured():
                clock=await alpaca.clock()
                market_open=bool(clock.get("is_open",False))
                open_now=_session_open(clock)
                if not open_now:
                    # نراقب في نافذة أوسع مما نتداول فيه: المتابعة مجانية والتنفيذ ليس كذلك
                    if settings.scan_extended_hours and extended_scan_active(datetime.now(NY)):
                        await _refresh_candidates("EXTENDED")
                        ARMED.clear(); IDLE_REASON="extended_hours_watch"
                    else:
                        IDLE_REASON="market_closed"
                if open_now:
                    LAST_RISK_STATUS=await alpaca.risk_status()
                    if LAST_RISK_STATUS.get("blocked"):
                        IDLE_REASON="daily_loss_guard"
                        AUTO_ENABLED=False; ARMED.clear(); log_event("daily_loss_guard",None,json.dumps(LAST_RISK_STATUS))
                    elif _opening_delay_active():
                        IDLE_REASON="opening_delay"
                        log_event("opening_delay",None,json.dumps({"minutes":settings.opening_delay_minutes}))
                    elif _entry_window_closed(clock):
                        IDLE_REASON="entry_window_closed"; ARMED.clear()
                    elif await _protection_halt():
                        IDLE_REASON="protection_lock"; ARMED.clear()
                    else:
                        rows,eligible=await _refresh_candidates("REGULAR" if market_open else "EXTENDED")
                        ARMED.retain_only({r["symbol"].upper() for r in eligible},"intel_or_setup_failed_recheck")
                        if not eligible: IDLE_REASON="no_arm_candidates"
                        elif not settings.enable_orders: IDLE_REASON="orders_disabled"
                        elif not ARMED.symbols(): IDLE_REASON="awaiting_confirmation"
                        else: IDLE_REASON="working"
                        if settings.enable_orders:
                            for candidate in eligible[:5]:
                                symbol=candidate["symbol"].upper()
                                if _cooldown_active(symbol):continue
                                if ARMED.arm_or_confirm(candidate):
                                    await maybe_place_paper_order(candidate); break
        except Exception as e:
            LAST_ERROR=str(e); IDLE_REASON="error"
            log_event("auto_error",None,json.dumps({"error":LAST_ERROR}))
        await asyncio.sleep(settings.scan_interval_seconds)

async def _protection_halt():
    """Refresh the circuit breakers from the trade record; True if trading is halted.

    A failure here must not stop the engine — the guards are a safety net, and a
    net that crashes the bot when it tears is worse than no net.
    """
    try:
        equity=float((LAST_RISK_STATUS or {}).get("equity") or settings.paper_equity)
        PROTECTIONS.update(from_ledger(await closed_trades()),datetime.now(timezone.utc),equity,settings)
    except Exception as e:
        log_event("protection_error",None,json.dumps({"error":str(e)})); return None
    halt=PROTECTIONS.blocked(None,datetime.now(timezone.utc))
    if halt:
        log_event("protection_halt",None,json.dumps({"code":halt.code,"until":halt.until.isoformat(),
                  "detail":halt.detail}))
    return halt


async def maybe_place_paper_order(candidate: dict):
    global LAST_PREFLIGHT
    if not settings.paper or not settings.enable_orders:return
    if candidate.get("decision",{}).get("action")!="ARM":
        log_event("order_blocked",candidate.get("symbol"),json.dumps({"reason":"intel_decision_not_arm"})); return
    if _opening_delay_active():
        log_event("order_blocked",candidate.get("symbol"),json.dumps({"reason":"opening_delay"})); return
    clock=await alpaca.clock()
    if not _session_open(clock):
        log_event("order_blocked",candidate.get("symbol"),json.dumps({"reason":"session_closed"})); return
    if _entry_window_closed(clock):
        log_event("order_blocked",candidate.get("symbol"),json.dumps({"reason":"entry_window_closed"})); return
    risk_status=await alpaca.risk_status()
    if risk_status.get("blocked"):
        log_event("order_blocked",candidate.get("symbol"),json.dumps({"reason":"daily_loss_limit","risk":risk_status})); return
    symbol=candidate["symbol"].upper()
    lock=PROTECTIONS.blocked(symbol,datetime.now(timezone.utc))
    if lock:
        log_event("order_blocked",symbol,json.dumps({"reason":lock.code,"scope":lock.scope,
                  "until":lock.until.isoformat(),"detail":lock.detail})); return
    if _cooldown_active(symbol):return
    entry=float(candidate.get("entry") or 0); stop=float(candidate.get("stop") or 0)
    if not(entry>stop>0):
        log_event("order_blocked",symbol,json.dumps({"reason":"invalid_structural_levels"})); return
    risk_pct=((entry-stop)/entry)*100
    if risk_pct>settings.max_stop_pct:
        log_event("order_blocked",symbol,json.dumps({"reason":"stop_too_wide","risk_pct":risk_pct})); return
    positions, open_orders, account = await asyncio.gather(
        alpaca.positions(), alpaca.open_orders(), alpaca.account(),
    )
    equity=float(account.get("equity",settings.paper_equity) or settings.paper_equity)
    buying_power=float(account.get("buying_power",equity) or equity)
    requested_qty=position_size(equity,entry,stop)
    preflight=evaluate_pretrade(
        candidate,positions,open_orders,equity=equity,buying_power=buying_power,
        requested_qty=requested_qty,config=settings,
    )
    LAST_PREFLIGHT=preflight.to_dict()
    if not preflight.allowed:
        log_event("order_blocked",symbol,json.dumps({"reason":"professional_preflight",
                  "blockers":preflight.blockers,"metrics":preflight.metrics})); return
    qty=preflight.approved_qty
    observed_at=datetime.now(timezone.utc)
    order_id=build_signal_order_id(symbol,str(candidate.get("setup") or "setup"),observed_at)
    # خارج الجلسة الرسمية لا يقبل الوسيط أمراً مرفقاً بوقف، فالدخول أمر limit
    # بسيط والوقف يُسجَّل ليطبّقه مدير الصفقات برمجياً.
    extended=not bool(clock.get("is_open",False))
    payload=(build_extended_hours_entry(symbol,qty,entry,source="intel",client_order_id=order_id)
             if extended else
             build_runner_order(symbol,qty,entry,stop,source="intel",client_order_id=order_id))
    result=await alpaca.submit_order(payload)
    soft_stops.remember(symbol,stop)
    COOLDOWNS[symbol]=datetime.now(timezone.utc)+timedelta(minutes=settings.symbol_cooldown_minutes)
    log_event("smart_paper_order",symbol,json.dumps({"order":result,"setup":candidate.get("setup"),
        "score":candidate.get("score"),"intel_score":candidate.get("intel_score"),"grade":candidate.get("grade"),
        "rvol":candidate.get("rvol"),"entry":entry,"stop":stop,"target_reference":candidate.get("target"),
        "runner_mode":True,"risk_pct":round(risk_pct,2),"preflight":preflight.to_dict(),
        "client_order_id":order_id,"extended_hours":extended,
        "stop_enforced_by":"software" if extended else "broker"}))
