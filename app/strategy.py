from __future__ import annotations
from dataclasses import dataclass
from statistics import mean
from .config import settings

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
    reasons: list[str]
    reject_reasons: list[str]
    vwap: float
    ema9: float
    ema20: float
    atr: float
    rvol: float
    vwap_extension_pct: float
    one_bar_move_pct: float
    pullback_seen: bool
    reclaim_confirmed: bool
    volume_confirmed: bool
    entry: float
    stop: float
    target: float
    risk_pct: float


def _num(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default


def _ema(values: list[float], length: int) -> float:
    if not values: return 0.0
    k = 2 / (length + 1); result = values[0]
    for v in values[1:]: result = v * k + result * (1-k)
    return result


def _atr(bars: list[dict], length: int = 14) -> float:
    if len(bars) < 2: return 0.0
    trs=[]; prev_close=_num(bars[0].get("c"))
    for b in bars[1:]:
        high,low,close=_num(b.get("h")),_num(b.get("l")),_num(b.get("c"))
        trs.append(max(high-low,abs(high-prev_close),abs(low-prev_close))); prev_close=close
    return mean(trs[-length:]) if trs else 0.0


def _vwap(bars: list[dict]) -> float:
    pv=vol=0.0
    for b in bars:
        v=_num(b.get("v"))
        if v<=0: continue
        typical=(_num(b.get("h"))+_num(b.get("l"))+_num(b.get("c")))/3
        pv += typical*v; vol += v
    return pv/vol if vol else 0.0


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

    reject=[]; reasons=[]
    if len(bars)<settings.min_bars: reject.append("Insufficient intraday history")
    if not(settings.min_price<=price<=settings.max_price): reject.append("Price outside allowed range")
    if not(settings.min_change_pct<=change_pct<=settings.max_change_pct): reject.append("Move too weak or already overextended")
    if spread_pct>settings.max_spread_pct: reject.append("Spread too wide")
    if rvol and rvol<settings.min_rvol: reject.append("RVOL below minimum")
    if vwap_ext>settings.max_vwap_extension_pct: reject.append("FOMO block: too far above VWAP")
    if ema20_ext>settings.max_ema20_extension_pct: reject.append("FOMO block: too far above EMA20")
    if one_bar_move>settings.max_one_bar_move_pct: reject.append("FOMO block: current 1m candle too large")
    if not pullback_seen: reject.append("No controlled pullback yet")
    if not reclaim_confirmed: reject.append("No VWAP/EMA reclaim confirmation")
    if not volume_confirmed: reject.append("Reclaim volume not confirmed")

    score=0.0
    if len(bars)>=settings.min_bars: score+=8
    if spread_pct<=0.20: score+=12
    elif spread_pct<=settings.max_spread_pct: score+=8
    if rvol>=4: score+=18
    elif rvol>=settings.min_rvol: score+=12
    if 0<=vwap_ext<=1.2: score+=17
    elif 0<=vwap_ext<=settings.max_vwap_extension_pct: score+=10
    if 0<=ema20_ext<=1.0: score+=12
    elif 0<=ema20_ext<=settings.max_ema20_extension_pct: score+=7
    if pullback_seen: score+=13
    if reclaim_confirmed: score+=13
    if volume_confirmed: score+=9
    if volume_rank<=10: score+=4
    if settings.min_change_pct<=change_pct<=20: score+=4
    score=round(min(score,100),1)

    if pullback_seen: reasons.append("Controlled pullback detected")
    if reclaim_confirmed: reasons.append("VWAP + EMA reclaim confirmed")
    if volume_confirmed: reasons.append("Reclaim volume confirmed")
    if rvol>0: reasons.append(f"RVOL {rvol:.2f}x")
    if 0<=vwap_ext<=settings.max_vwap_extension_pct: reasons.append(f"VWAP extension only {vwap_ext:.2f}%")
    if spread_pct<=settings.max_spread_pct: reasons.append(f"Spread {spread_pct:.2f}%")

    recent_lows=[_num(b.get("l")) for b in bars[-8:] if _num(b.get("l"))>0]
    swing_low=min(recent_lows) if recent_lows else 0.0
    structural_stop=swing_low-(atr*0.25) if swing_low>0 and atr>0 else 0.0
    fallback_stop=price*0.985
    stop=structural_stop if 0<structural_stop<price else fallback_stop
    risk_pct=((price-stop)/price)*100 if price>0 else 999.0
    if risk_pct<settings.min_stop_pct:
        stop=price*(1-settings.min_stop_pct/100); risk_pct=settings.min_stop_pct
    if risk_pct>settings.max_stop_pct: reject.append("Required stop is too wide")

    entry=round(price,2); stop=round(stop,2); risk_dollars=max(entry-stop,0)
    target=round(entry+risk_dollars*settings.reward_r_multiple,2) if risk_dollars>0 else 0.0
    eligible=score>=settings.min_score and not reject and target>entry>stop>0
    setup="PULLBACK_RECLAIM" if eligible or (pullback_seen and reclaim_confirmed) else "WAIT"

    return Candidate(symbol=symbol,price=round(price,4),change_pct=round(change_pct,2),volume_rank=volume_rank,spread_pct=round(spread_pct,3),score=score,eligible=eligible,setup=setup,reasons=reasons,reject_reasons=reject,vwap=round(vwap,4),ema9=round(ema9,4),ema20=round(ema20,4),atr=round(atr,4),rvol=round(rvol,2),vwap_extension_pct=round(vwap_ext,2),one_bar_move_pct=round(one_bar_move,2),pullback_seen=pullback_seen,reclaim_confirmed=reclaim_confirmed,volume_confirmed=volume_confirmed,entry=entry,stop=stop,target=target,risk_pct=round(risk_pct,2))


def position_size(equity: float, entry: float, stop: float) -> int:
    if equity<=0 or entry<=0 or stop<=0 or stop>=entry: return 0
    risk_dollars=equity*settings.risk_per_trade; per_share=entry-stop
    raw=int(risk_dollars/per_share); cap=int((equity*0.15)/entry)
    return max(0,min(raw,cap))
