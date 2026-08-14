from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from statistics import mean
from .alpaca import alpaca
from .config import settings
from .indicators import num
from .messages import render
from .microstructure import analyze_microstructure
from .session import NY, session_fraction
from .strategy import build_candidate
from .strategy_selector import classify_strategy


def assemble_candidates(symbols: list[str], change_map: dict[str, float], rank_map: dict[str, int],
                        snapshots: dict[str, dict], bars_map: dict[str, list[dict]],
                        daily_map: dict[str, list[dict]], regime: dict, fraction: float,
                        micro_map: dict[str, dict] | None = None) -> list[dict]:
    """Turn raw market data into ranked candidate rows.

    Pure function: the live scanner feeds it broker data, the backtester feeds it
    replayed historical data, so both exercise identical selection logic. The
    optional micro_map is diagnostic-only and is intentionally absent in
    historical replays until quote/trade history is explicitly modelled.
    """
    output = []
    micro_map = micro_map or {}
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
        row["microstructure"] = micro_map.get(s, {
            "state": "UNAVAILABLE", "quality_score": None, "execution_gate": False,
            "note": "No live quote/trade snapshot attached to this candidate."
        })
        row["strategy_profile"] = classify_strategy(row)
        if row["eligible"] and not regime.get("longs_allowed", False):
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
    regime = await alpaca.market_regime()
    movers = await alpaca.movers(settings.screener_top)
    actives = await alpaca.most_actives(settings.screener_top)
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
    symbols=symbols[:max(settings.screener_top,25)]

    snapshots=await alpaca.snapshots(symbols)
    snapmap=snapshots.get("snapshots",snapshots)
    for s in active_only: change_map[s]=change_pct_from_snapshot(snapmap.get(s))
    bars_map=await alpaca.intraday_bars(symbols,minutes=300)
    daily_map=await alpaca.daily_bars(symbols,days=20)

    # Latest NBBO/trade snapshots are live-only diagnostics for now. Failure to
    # fetch them must never take the scanner down or silently change eligibility.
    micro_map={}
    try:
        quotes=await alpaca.latest_quotes(symbols)
        trades=await alpaca.latest_trades(symbols)
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

    return assemble_candidates(symbols, change_map, active_rank, snapmap, bars_map, daily_map,
                               regime, session_fraction(datetime.now(NY)), micro_map)
