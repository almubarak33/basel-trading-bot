from __future__ import annotations
from dataclasses import dataclass
from statistics import mean
from .config import settings
from .indicators import num as _num, ema as _ema, vwap as _vwap
from .messages import MessageList
from .pricing import round_price

@dataclass
class Candidate:
    symbol: str
    price: float
    change_pct: float
    volume_rank: int
    spread_pct: float
    score: float
    eligible: bool
    setup: str
    # Human-readable English, kept for existing consumers and logs.
    reasons: list[str]
    reject_reasons: list[str]
    # Language-neutral equivalents the client renders in the active language.
    reason_codes: list[dict]
    reject_codes: list[dict]
    vwap: float
    ema9: float
    ema20: float
    atr: float
    rvol: float
    vwap_extension_pct: float
    one_bar_move_pct: float
    pullback_seen: bool
    reclaim_confirmed: bool
    breakout_confirmed: bool
    volume_confirmed: bool
    entry: float
    stop: float
    target: float
    risk_pct: float


def _atr(bars: list[dict], length: int = 14) -> float:
    if len(bars) < 2: return 0.0
    trs=[]; prev_close=_num(bars[0].get("c"))
    for b in bars[1:]:
        high,low,close=_num(b.get("h")),_num(b.get("l")),_num(b.get("c"))
        trs.append(max(high-low,abs(high-prev_close),abs(low-prev_close))); prev_close=close
    return mean(trs[-length:]) if trs else 0.0


def price_in_scope(price: float) -> bool:
    return price >= settings.min_price and (settings.max_price <= 0 or price <= settings.max_price)


def move_in_scope(change_pct: float) -> bool:
    return change_pct >= settings.min_change_pct and (
        settings.max_change_pct <= 0 or change_pct <= settings.max_change_pct
    )


def max_spread_for_price(price: float) -> float:
    if price < 1: return settings.max_spread_penny_pct
    if price < 5: return settings.max_spread_low_price_pct
    return settings.max_spread_pct


def build_candidate(symbol: str, change_pct: float, volume_rank: int, snapshot: dict, bars: list[dict], avg_daily_volume: float = 0.0, session_fraction: float = 1.0) -> Candidate:
    latest_trade=snapshot.get("latestTrade") or {}; latest_quote=snapshot.get("latestQuote") or {}; minute=snapshot.get("minuteBar") or {}; daily=snapshot.get("dailyBar") or {}
    price=_num(latest_trade.get("p") or minute.get("c") or daily.get("c"))
    bid=_num(latest_quote.get("bp")); ask=_num(latest_quote.get("ap"))
    spread_pct=((ask-bid)/((ask+bid)/2)*100) if ask>0 and bid>0 and ask>=bid else 999.0

    bars=[b for b in bars if _num(b.get("c"))>0]
    closes=[_num(b.get("c")) for b in bars]; volumes=[_num(b.get("v")) for b in bars]
    vwap=_vwap(bars); ema9=_ema(closes[-60:],9) if closes else 0.0; ema20=_ema(closes[-80:],20) if closes else 0.0; atr=_atr(bars,14)
    vwap_ext=((price/vwap)-1)*100 if vwap>0 else 999.0
    ema20_ext=((price/ema20)-1)*100 if ema20>0 else 999.0

    current_session_volume=sum(volumes)
    expected_so_far=max(avg_daily_volume * max(min(session_fraction,1.0),0.05),1.0)
    rvol=current_session_volume/expected_so_far if avg_daily_volume>0 else 0.0

    one_bar_move=999.0
    if bars:
        o=_num(bars[-1].get("o")); c=_num(bars[-1].get("c"))
        if o>0: one_bar_move=abs(c/o-1)*100

    recent=bars[-10:] if len(bars)>=10 else bars
    support=max(vwap,ema20)
    pullback_seen=bool(support>0 and recent and any(abs(_num(b.get("l"))/support-1)<=0.012 for b in recent[:-1]))
    reclaim_confirmed=bool(price>ema9>ema20>0 and price>vwap>0)
    avg_vol=mean(volumes[-11:-1]) if len(volumes)>=11 else (mean(volumes[:-1]) if len(volumes)>1 else 0)
    last_vol=volumes[-1] if volumes else 0
    volume_confirmed=bool(avg_vol>0 and last_vol>=avg_vol*0.85)

    allowed_spread=max_spread_for_price(price)
    trend_aligned=bool(price>vwap>0 and ema9>=ema20>0 and price>=ema9*0.995)
    pullback_setup=bool(pullback_seen and reclaim_confirmed and volume_confirmed)
    breakout_confirmed=bool(
        trend_aligned and volume_confirmed and rvol>=settings.min_rvol
        and change_pct>=settings.min_execution_change_pct and move_in_scope(change_pct)
        and 0<=vwap_ext<=settings.max_vwap_extension_pct
        and one_bar_move<=settings.max_one_bar_move_pct
    )
    reject=MessageList(); reasons=MessageList()
    if len(bars)<settings.min_bars: reject.add("insufficient_history")
    if not price_in_scope(price): reject.add("price_out_of_range")
    if not move_in_scope(change_pct): reject.add("move_out_of_range")
    if move_in_scope(change_pct) and change_pct<settings.min_execution_change_pct:
        reject.add("entry_momentum_too_low")
    if spread_pct>allowed_spread: reject.add("spread_too_wide")
    if rvol and rvol<settings.min_rvol: reject.add("rvol_too_low")
    if vwap_ext>settings.max_vwap_extension_pct: reject.add("vwap_extended")
    if ema20_ext>settings.max_ema20_extension_pct: reject.add("ema20_extended")
    if one_bar_move>settings.max_one_bar_move_pct: reject.add("bar_too_large")
    if not pullback_seen and not breakout_confirmed: reject.add("no_pullback")
    if not reclaim_confirmed and not breakout_confirmed: reject.add("no_reclaim")
    if not volume_confirmed: reject.add("no_volume_confirm")

    score=0.0
    if len(bars)>=settings.min_bars: score+=8
    if spread_pct<=min(0.20,allowed_spread): score+=12
    elif spread_pct<=allowed_spread: score+=8
    if rvol>=4: score+=18
    elif rvol>=settings.min_rvol: score+=12
    if 0<=vwap_ext<=1.2: score+=17
    elif 0<=vwap_ext<=settings.max_vwap_extension_pct: score+=10
    if 0<=ema20_ext<=1.0: score+=12
    elif 0<=ema20_ext<=settings.max_ema20_extension_pct: score+=7
    if pullback_seen: score+=13
    if reclaim_confirmed: score+=13
    if volume_confirmed: score+=9
    if breakout_confirmed: score+=15
    if volume_rank<=10: score+=4
    if move_in_scope(change_pct): score+=4
    score=round(min(score,100),1)

    if pullback_seen: reasons.add("pullback_detected")
    if reclaim_confirmed: reasons.add("reclaim_confirmed")
    if breakout_confirmed: reasons.add("momentum_breakout")
    if volume_confirmed: reasons.add("volume_confirmed")
    if rvol>0: reasons.add("rvol", value=f"{rvol:.2f}x")
    if 0<=vwap_ext<=settings.max_vwap_extension_pct: reasons.add("vwap_extension", value=f"{vwap_ext:.2f}%")
    if spread_pct<=allowed_spread: reasons.add("spread", value=f"{spread_pct:.2f}%")

    recent_lows=[_num(b.get("l")) for b in bars[-8:] if _num(b.get("l"))>0]
    swing_low=min(recent_lows) if recent_lows else 0.0
    structural_stop=swing_low-(atr*0.25) if swing_low>0 and atr>0 else 0.0
    fallback_stop=price*0.985
    stop=structural_stop if 0<structural_stop<price else fallback_stop
    risk_pct=((price-stop)/price)*100 if price>0 else 999.0
    if risk_pct<settings.min_stop_pct:
        stop=price*(1-settings.min_stop_pct/100); risk_pct=settings.min_stop_pct
    if risk_pct>settings.max_stop_pct: reject.add("stop_too_wide")

    entry=round_price(price); stop=round_price(stop); risk_dollars=max(entry-stop,0)
    target=round_price(entry+risk_dollars*settings.reward_r_multiple) if risk_dollars>0 else 0.0
    eligible=score>=settings.min_score and not reject and target>entry>stop>0
    setup="MOMENTUM_BREAKOUT" if breakout_confirmed and not pullback_setup else (
        "PULLBACK_RECLAIM" if pullback_setup else "WAIT"
    )

    return Candidate(symbol=symbol,price=round(price,4),change_pct=round(change_pct,2),volume_rank=volume_rank,spread_pct=round(spread_pct,3),score=score,eligible=eligible,setup=setup,reasons=reasons.texts(),reject_reasons=reject.texts(),reason_codes=reasons.codes,reject_codes=reject.codes,vwap=round(vwap,4),ema9=round(ema9,4),ema20=round(ema20,4),atr=round(atr,4),rvol=round(rvol,2),vwap_extension_pct=round(vwap_ext,2),one_bar_move_pct=round(one_bar_move,2),pullback_seen=pullback_seen,reclaim_confirmed=reclaim_confirmed,breakout_confirmed=breakout_confirmed,volume_confirmed=volume_confirmed,entry=entry,stop=stop,target=target,risk_pct=round(risk_pct,2))


def position_size(equity: float, entry: float, stop: float) -> int:
    if equity<=0 or entry<=0 or stop<=0 or stop>=entry: return 0
    risk_dollars=equity*settings.risk_per_trade; per_share=entry-stop
    raw=int(risk_dollars/per_share); cap=int((equity*settings.max_position_notional_pct)/entry)
    return max(0,min(raw,cap))
