"""Pure stock-detail helpers shared by the API, simulation, and tests."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .indicators import num


CHART_TIMEFRAMES = {
    "1Min": {"label": "1 دقيقة", "days": 2, "ttl": 15},
    "5Min": {"label": "5 دقائق", "days": 10, "ttl": 20},
    "15Min": {"label": "15 دقيقة", "days": 30, "ttl": 30},
    "30Min": {"label": "30 دقيقة", "days": 60, "ttl": 45},
    "1Hour": {"label": "ساعة", "days": 120, "ttl": 60},
    "4Hour": {"label": "4 ساعات", "days": 365, "ttl": 120},
    "1Day": {"label": "يومي", "days": 730, "ttl": 300},
    "1Week": {"label": "أسبوعي", "days": 3650, "ttl": 900},
    "1Month": {"label": "شهري", "days": 3650, "ttl": 1800},
}


def timeframe_config(value: str) -> dict | None:
    return CHART_TIMEFRAMES.get(value)


def timeframe_catalog() -> list[dict]:
    return [{"value": key, **value} for key, value in CHART_TIMEFRAMES.items()]


def price_statistics(daily_bars: list[dict], snapshot: dict | None = None) -> dict:
    bars = [b for b in daily_bars or [] if num(b.get("c")) > 0]
    current = (snapshot or {}).get("dailyBar") or (bars[-1] if bars else {})
    previous = (snapshot or {}).get("prevDailyBar") or (bars[-2] if len(bars) > 1 else {})
    year = bars[-252:]
    volumes = [num(b.get("v")) for b in bars[-20:] if num(b.get("v")) > 0]
    return {
        "open": num(current.get("o")), "high": num(current.get("h")),
        "low": num(current.get("l")), "close": num(current.get("c")),
        "volume": num(current.get("v")), "previous_close": num(previous.get("c")),
        "average_volume_20d": round(sum(volumes) / len(volumes), 0) if volumes else None,
        "high_52w": max((num(b.get("h")) for b in year), default=0) or None,
        "low_52w": min((num(b.get("l")) for b in year if num(b.get("l")) > 0), default=0) or None,
        "sessions": len(bars), "as_of": current.get("t"),
    }


def flatten_corporate_actions(payload: dict | list | None) -> list[dict]:
    if isinstance(payload, list):
        rows = payload
    else:
        root = (payload or {}).get("corporate_actions", payload or {})
        rows = []
        if isinstance(root, dict):
            for action_type, items in root.items():
                if not isinstance(items, list):
                    continue
                normalized = action_type.rstrip("s")
                rows.extend({**item, "type": item.get("type") or normalized}
                            for item in items if isinstance(item, dict))
    return sorted(rows, key=lambda row: str(
        row.get("process_date") or row.get("ex_date") or row.get("record_date") or ""
    ), reverse=True)


def simulation_chart_bars(symbol: str, timeframe: str, base: float) -> list[dict]:
    seconds = {
        "1Min": 60, "5Min": 300, "15Min": 900, "30Min": 1800,
        "1Hour": 3600, "4Hour": 14400, "1Day": 86400,
        "1Week": 604800, "1Month": 2592000,
    }[timeframe]
    count = 220
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    seed = sum(ord(char) for char in symbol.upper()) % 17
    rows = []
    previous = max(base * 0.82, 0.01)
    for index in range(count):
        phase = index + seed
        drift = (index / max(count - 1, 1)) * 0.17
        close = max(base * (0.82 + drift + math.sin(phase / 9) * 0.018), 0.01)
        open_ = previous
        high = max(open_, close) * (1.002 + abs(math.sin(phase)) * 0.004)
        low = min(open_, close) * (0.998 - abs(math.cos(phase)) * 0.003)
        moment = end - timedelta(seconds=seconds * (count - index - 1))
        rows.append({
            "t": moment.isoformat(), "o": round(open_, 4), "h": round(high, 4),
            "l": round(max(low, 0.0001), 4), "c": round(close, 4),
            "v": int(20_000 + abs(math.sin(phase / 4)) * 80_000),
        })
        previous = close
    return rows
