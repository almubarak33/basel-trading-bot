from __future__ import annotations
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from statistics import mean
from .alpaca import alpaca
from .catalyst import analyze_catalyst
from .config import settings
from .data_quality import assess_market_data
from .indicators import num
from .messages import render
from .microstructure import analyze_microstructure
from .session import NY, session_fraction
from .strategy import build_candidate
from .strategy_selector import classify_strategy


def assemble_candidates(symbols: list[str], change_map: dict[str, float], rank_map: dict[str, int],
                        snapshots: dict[str, dict], bars_map: dict[str, list[dict]],
                        daily_map: dict[str, list[dict]], regime: dict, fraction: float,
                        micro_map: dict[str, dict] | None = None,
                        catalyst_map: dict[str, dict] | None = None,
                        observed_at: datetime | None = None) -> list[dict]:
    """Turn raw market data into ranked candidate rows.

    Microstructure and catalyst inputs are observational only. Historical replays
    can omit them without changing execution eligibility until those layers are
    explicitly validated and promoted into the execution gate.
    """
    output = []
    micro_map = micro_map or {}
    catalyst_map = catalyst_map or {}
    for s in symbols:
        hist = daily_map.get(s, [])
        vols = [float(b.get("v") or 0) for b in hist[-20:] if float(b.get("v") or 0) > 0]
        avg_daily = mean(vols) if vols else 0.0
        candidate = build_candidate(
            s, change_map.get(s, 0.0), rank_map.get(s, settings.screener_top+1),
            snapshots.get(s, {}), bars_map.get(s, []), avg_daily_volume=avg_daily, session_fraction=fraction
        )
        row = asdict(candidate)
        row["market_regime"] = regime
        row["session_fraction"] = round(fraction, 3)
        row["avg_daily_volume_20d"] = round(avg_daily, 0)
        row["latest_bar_volume"] = round(float((bars_map.get(s) or [{}])[-1].get("v") or 0), 0)
        row["data_quality"] = assess_market_data(
            snapshots.get(s, {}), bars_map.get(s, []), observed_at=observed_at,
            max_quote_age_seconds=settings.max_market_data_age_seconds,
            max_bar_age_seconds=settings.max_intraday_bar_age_seconds,
        )
        row["microstructure"] = micro_map.get(s, {
            "state": "UNAVAILABLE", "quality_score": None, "execution_gate": False,
            "note": "No live quote/trade snapshot attached to this candidate."
        })
        row["catalyst"] = catalyst_map.get(s, {
            "status": "UNAVAILABLE", "score": None, "direction": "UNKNOWN",
            "headline": None, "execution_gate": False,
            "note": "Catalyst history not attached to this candidate."
        })
        row["strategy_profile"] = classify_strategy(row)
        if row["eligible"] and not regime.get("longs_allowed", False):
            observed_regime = any(
                isinstance(detail, dict) and detail.get("price")
                for detail in (regime.get("details") or {}).values()
            )
            if settings.trading_profile == "AGGRESSIVE" and observed_regime:
                row["market_regime_caution"] = True
            else:
                row["eligible"] = False
                row["reject_reasons"].append(render("regime_block"))
                row["reject_codes"].append({"code": "regime_block"})
        output.append(row)
    output.sort(key=lambda x: (x["eligible"], x["score"], x.get("rvol", 0), -abs(x["vwap_extension_pct"])), reverse=True)
    return output


def change_pct_from_snapshot(snapshot: dict) -> float:
    snapshot = snapshot or {}
    prev_close = num((snapshot.get("prevDailyBar") or {}).get("c"))
    if prev_close <= 0: return 0.0
    price = (num((snapshot.get("latestTrade") or {}).get("p"))
             or num((snapshot.get("minuteBar") or {}).get("c"))
             or num((snapshot.get("dailyBar") or {}).get("c")))
    if price <= 0: return 0.0
    return (price / prev_close - 1) * 100


async def scan():
    # Independent requests are concurrent to keep a 100-symbol scan inside the
    # decision window without changing the point-in-time inputs.
    regime, movers, actives = await asyncio.gather(
        alpaca.market_regime(),
        alpaca.movers(settings.movers_top),
        alpaca.most_actives(settings.actives_top),
    )
    gainers = movers.get("gainers", [])
    active_rows = actives.get("most_actives", actives.get("mostActives", []))
    active_rank = {row.get("symbol"): i for i, row in enumerate(active_rows, 1) if row.get("symbol")}
    symbols, change_map = [], {}
    for row in gainers:
        s=row.get("symbol")
        if not s: continue
        if s not in symbols: symbols.append(s)
        change_map[s]=float(row.get("percent_change", row.get("percentChange",0)) or 0)
    active_only=[]
    for row in active_rows:
        s=row.get("symbol")
        if s and s not in symbols:
            symbols.append(s); active_only.append(s)
    symbols=symbols[:max(1,settings.screener_universe_limit)]

    snapshots, bars_map, daily_map = await asyncio.gather(
        alpaca.snapshots(symbols),
        alpaca.intraday_bars(symbols,minutes=300),
        alpaca.daily_bars(symbols,days=20),
    )
    snapmap=snapshots.get("snapshots",snapshots)
    for s in active_only: change_map[s]=change_pct_from_snapshot(snapmap.get(s))

    micro_map={}
    quotes_result, trades_result, news_result = await asyncio.gather(
        alpaca.latest_quotes(symbols), alpaca.latest_trades(symbols),
        alpaca.news(symbols,hours=24,limit=50), return_exceptions=True,
    )
    try:
        if isinstance(quotes_result, Exception): raise quotes_result
        if isinstance(trades_result, Exception): raise trades_result
        quotes, trades = quotes_result, trades_result
        for s in symbols:
            snap=snapmap.get(s,{})
            price=(num((snap.get("latestTrade") or {}).get("p"))
                   or num((snap.get("minuteBar") or {}).get("c"))
                   or num((snap.get("dailyBar") or {}).get("c")))
            micro_map[s]=analyze_microstructure(quotes.get(s),trades.get(s),price)
    except Exception as exc:
        for s in symbols:
            micro_map[s]={"state":"UNAVAILABLE","quality_score":None,"execution_gate":False,
                          "note":f"Microstructure unavailable: {type(exc).__name__}"}

    catalyst_map={}
    try:
        if isinstance(news_result, Exception): raise news_result
        news_map=news_result
        for s in symbols:
            catalyst_map[s]=analyze_catalyst(news_map.get(s,[]))
    except Exception as exc:
        for s in symbols:
            catalyst_map[s]={"status":"UNAVAILABLE","score":None,"direction":"UNKNOWN",
                             "headline":None,"execution_gate":False,
                             "note":f"Catalyst unavailable: {type(exc).__name__}"}

    observed_at=datetime.now(timezone.utc)
    return assemble_candidates(symbols, change_map, active_rank, snapmap, bars_map, daily_map,
                               regime, session_fraction(datetime.now(NY)), micro_map, catalyst_map,
                               observed_at=observed_at)
