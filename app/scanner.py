from __future__ import annotations
from dataclasses import asdict
from .alpaca import alpaca
from .config import settings
from .strategy import build_candidate

async def scan():
    movers = await alpaca.movers(settings.screener_top)
    actives = await alpaca.most_actives(settings.screener_top)

    gainers = movers.get("gainers", [])
    active_rows = actives.get("most_actives", actives.get("mostActives", []))

    active_rank = {}
    for i, row in enumerate(active_rows, 1):
        symbol = row.get("symbol")
        if symbol:
            active_rank[symbol] = i

    symbols = []
    change_map = {}

    # Start with movers, then add the most active names. Avoid a giant universe in v1.
    for row in gainers:
        s = row.get("symbol")
        if not s:
            continue
        if s not in symbols:
            symbols.append(s)
        change_map[s] = float(row.get("percent_change", row.get("percentChange", 0)) or 0)

    for row in active_rows:
        s = row.get("symbol")
        if s and s not in symbols:
            symbols.append(s)
            change_map[s] = 0.0

    symbols = symbols[: max(settings.screener_top, 25)]

    snapshots = await alpaca.snapshots(symbols)
    snapmap = snapshots.get("snapshots", snapshots)
    bars_map = await alpaca.intraday_bars(symbols, minutes=300)

    output = []
    for s in symbols:
        rank = active_rank.get(s, settings.screener_top + 1)
        candidate = build_candidate(
            s,
            change_map.get(s, 0.0),
            rank,
            snapmap.get(s, {}),
            bars_map.get(s, []),
        )
        output.append(asdict(candidate))

    # READY setups first. WATCH list is then sorted by entry quality, not raw % gain.
    output.sort(key=lambda x: (x["eligible"], x["score"], -abs(x["vwap_extension_pct"])), reverse=True)
    return output
