from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from statistics import mean
from .alpaca import alpaca
from .config import settings
from .session import NY, session_fraction
from .strategy import build_candidate


def assemble_candidates(symbols: list[str], change_map: dict[str, float], rank_map: dict[str, int],
                        snapshots: dict[str, dict], bars_map: dict[str, list[dict]],
                        daily_map: dict[str, list[dict]], regime: dict, fraction: float) -> list[dict]:
    """Turn raw market data into ranked candidate rows.

    Pure function: the live scanner feeds it broker data, the backtester feeds it
    replayed historical data, so both exercise identical selection logic.
    """
    output = []
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
        if row["eligible"] and not regime.get("longs_allowed", False):
            row["eligible"] = False
            row["reject_reasons"].append("Market regime block: SPY/QQQ not supportive")
        output.append(row)
    output.sort(key=lambda x: (x["eligible"], x["score"], x.get("rvol", 0), -abs(x["vwap_extension_pct"])), reverse=True)
    return output


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
    for row in active_rows:
        s=row.get("symbol")
        if s and s not in symbols:
            symbols.append(s); change_map[s]=0.0
    symbols=symbols[:max(settings.screener_top,25)]

    snapshots=await alpaca.snapshots(symbols)
    snapmap=snapshots.get("snapshots",snapshots)
    bars_map=await alpaca.intraday_bars(symbols,minutes=300)
    daily_map=await alpaca.daily_bars(symbols,days=20)

    return assemble_candidates(symbols, change_map, active_rank, snapmap, bars_map, daily_map,
                               regime, session_fraction(datetime.now(NY)))
