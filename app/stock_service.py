"""Progressive stock-page payloads: fast core, lazy detail, and chart data."""
from __future__ import annotations

import asyncio
from datetime import datetime

from .alpaca import alpaca
from .async_cache import AsyncTTLCache
from .chart_data import completed_session_closes
from .indicators import num
from .intelligence import enrich_candidate
from .microstructure import analyze_microstructure
from .scanner import assemble_candidates, change_pct_from_snapshot
from .sec_data import company_profile
from .session import NY, session_fraction
from . import simulation
from .stock_data import (
    flatten_corporate_actions,
    price_statistics,
    simulation_chart_bars,
    timeframe_catalog,
    timeframe_config,
)

_CACHE = AsyncTTLCache()


def _value(result, default):
    return default if isinstance(result, Exception) else result


def _position(payload) -> dict | None:
    if not isinstance(payload, dict) or not payload.get("symbol"):
        return None
    return {
        "symbol": str(payload.get("symbol") or "").upper(),
        "qty": abs(num(payload.get("qty"))),
        "entry": num(payload.get("avg_entry_price")),
        "current": num(payload.get("current_price")),
        "pnl": num(payload.get("unrealized_pl")),
        "pnl_pct": num(payload.get("unrealized_plpc")) * 100,
    }


def _asset(payload, symbol: str) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    return {
        "symbol": symbol, "name": payload.get("name") or symbol,
        "exchange": payload.get("exchange"), "status": payload.get("status"),
        "asset_class": payload.get("class"), "tradable": payload.get("tradable"),
        "marginable": payload.get("marginable"), "shortable": payload.get("shortable"),
        "easy_to_borrow": payload.get("easy_to_borrow"),
        "fractionable": payload.get("fractionable"),
        "attributes": payload.get("attributes") or [],
    }


def _simulation_core(symbol: str) -> dict:
    rows = [enrich_candidate(row) for row in simulation.scan()]
    candidate = next((row for row in rows if row.get("symbol", "").upper() == symbol), None)
    if candidate is None:
        raise LookupError("simulation_symbol_not_found")
    base = float(candidate.get("price") or 1)
    bars = simulation_chart_bars(symbol, "1Min", base)
    daily = simulation_chart_bars(symbol, "1Day", base)
    return {
        "simulation": True, "symbol": symbol, "candidate": candidate,
        "asset": {"symbol": symbol, "name": f"{symbol} Simulation", "exchange": "SIM",
                  "status": "active", "tradable": False, "shortable": False,
                  "marginable": False, "fractionable": False, "attributes": []},
        "bars": bars, "bars_timeframe": "1Min",
        "previous_closes": completed_session_closes(daily),
        "price_stats": price_statistics(daily), "position": None,
        "timeframes": timeframe_catalog(),
        "loaded_at": datetime.now(NY).isoformat(),
    }


async def stock_core(symbol: str) -> dict:
    symbol = symbol.upper()
    if not alpaca.configured():
        return _simulation_core(symbol)

    async def load():
        results = await asyncio.gather(
            alpaca.snapshots([symbol]), alpaca.intraday_bars([symbol], minutes=5 * 24 * 60),
            alpaca.daily_bars([symbol], days=25), alpaca.market_regime(),
            alpaca.asset(symbol), alpaca.position(symbol), return_exceptions=True,
        )
        snapshots, intraday, daily, regime, asset_payload, position = results
        snapshots = _value(snapshots, {})
        snapmap = snapshots.get("snapshots", snapshots) if isinstance(snapshots, dict) else {}
        snapshot = snapmap.get(symbol, {})
        bars_map = _value(intraday, {})
        daily_map = _value(daily, {})
        bars = bars_map.get(symbol, []) if isinstance(bars_map, dict) else []
        daily_bars = daily_map.get(symbol, []) if isinstance(daily_map, dict) else []
        regime = _value(regime, {"longs_allowed": True, "healthy_indexes": None, "details": {}})
        micro = analyze_microstructure(snapshot.get("latestQuote"), snapshot.get("latestTrade"),
                                       num((snapshot.get("latestTrade") or {}).get("p")))
        candidates = assemble_candidates(
            [symbol], {symbol: change_pct_from_snapshot(snapshot)}, {symbol: 1},
            {symbol: snapshot}, {symbol: bars}, {symbol: daily_bars}, regime,
            session_fraction(datetime.now(NY)), {symbol: micro},
        )
        candidate = enrich_candidate(candidates[0]) if candidates else None
        if candidate is None:
            raise LookupError("symbol_market_data_not_found")
        return {
            "simulation": False, "symbol": symbol, "candidate": candidate,
            "asset": _asset(_value(asset_payload, {}), symbol),
            "bars": bars, "bars_timeframe": "1Min",
            "previous_closes": completed_session_closes(daily_bars),
            "price_stats": price_statistics(daily_bars, snapshot),
            "position": _position(_value(position, None)),
            "timeframes": timeframe_catalog(),
            "loaded_at": datetime.now(NY).isoformat(),
        }
    return await _CACHE.get(f"stock:core:{symbol}", 8, load)


async def stock_chart(symbol: str, timeframe: str) -> dict:
    config = timeframe_config(timeframe)
    if config is None:
        raise ValueError("unsupported_timeframe")
    symbol = symbol.upper()
    core = await stock_core(symbol)
    if core["simulation"]:
        bars = simulation_chart_bars(symbol, timeframe, float(core["candidate"].get("price") or 1))
    else:
        async def load():
            return await alpaca.chart_bars(symbol, timeframe, config["days"])
        bars = await _CACHE.get(f"stock:chart:{symbol}:{timeframe}", config["ttl"], load)
    return {
        "symbol": symbol, "timeframe": timeframe, "label": config["label"],
        "bars": bars, "simulation": core["simulation"],
        "loaded_at": datetime.now(NY).isoformat(),
    }


async def stock_details(symbol: str) -> dict:
    symbol = symbol.upper()
    core = await stock_core(symbol)
    if core["simulation"]:
        return {
            "simulation": True, "symbol": symbol, "price_stats": core["price_stats"],
            "corporate_actions": [], "news": [],
            "trading_status": {
                "state": "SIMULATION", "tradable": False, "shortable": False,
                "marginable": False, "fractionable": False, "halt_data_available": False,
            },
            "compliance": {"status": "UNVERIFIED"},
            "loaded_at": datetime.now(NY).isoformat(),
        }

    async def load():
        daily, actions, news = await asyncio.gather(
            alpaca.daily_bars([symbol], days=400), alpaca.corporate_actions(symbol),
            alpaca.news([symbol], hours=7 * 24, limit=30), return_exceptions=True,
        )
        daily_map = _value(daily, {})
        daily_bars = daily_map.get(symbol, []) if isinstance(daily_map, dict) else []
        stats = price_statistics(daily_bars)
        for key in ("open", "high", "low", "close", "volume", "previous_close", "as_of"):
            value = (core.get("price_stats") or {}).get(key)
            if value not in (None, 0, ""):
                stats[key] = value
        corporate = flatten_corporate_actions(_value(actions, {}))
        news_map = _value(news, {})
        reverse_split = next((row for row in corporate if "reverse_split" in str(row.get("type"))), None)
        asset = core.get("asset") or {}
        return {
            "simulation": False, "symbol": symbol, "price_stats": stats,
            "corporate_actions": corporate[:20],
            "latest_reverse_split": reverse_split,
            "news": (news_map.get(symbol, []) if isinstance(news_map, dict) else [])[:15],
            "trading_status": {
                "state": asset.get("status") or "unknown", "tradable": asset.get("tradable"),
                "shortable": asset.get("shortable"), "marginable": asset.get("marginable"),
                "fractionable": asset.get("fractionable"),
                "overnight_halted": "overnight_halted" in (asset.get("attributes") or []),
                "halt_data_available": False,
            },
            "compliance": {"status": "UNVERIFIED", "reason": "no_verified_sharia_source"},
            "loaded_at": datetime.now(NY).isoformat(),
        }
    return await _CACHE.get(f"stock:details:{symbol}", 120, load)


async def stock_fundamentals(symbol: str) -> dict:
    symbol = symbol.upper()
    core = await stock_core(symbol)
    if core["simulation"]:
        return {"available": False, "source": "SEC EDGAR", "reason": "simulation"}
    price = num((core.get("candidate") or {}).get("price"))
    return await company_profile(symbol, price)
