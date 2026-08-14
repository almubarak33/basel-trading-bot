from __future__ import annotations
from datetime import datetime, timedelta, timezone
import httpx
from .config import settings

DATA = "https://data.alpaca.markets"
PAPER = "https://paper-api.alpaca.markets"

class Alpaca:
    def __init__(self):
        self.headers = {
            "APCA-API-KEY-ID": settings.api_key,
            "APCA-API-SECRET-KEY": settings.api_secret,
        }

    def configured(self) -> bool:
        return bool(settings.api_key and settings.api_secret)

    async def _get(self, url: str, params=None):
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            return r.json()

    async def _post(self, url: str, payload: dict):
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, headers=self.headers, json=payload)
            r.raise_for_status()
            return r.json()

    async def movers(self, top: int):
        return await self._get(f"{DATA}/v1beta1/screener/stocks/movers", {"top": min(top, 50)})

    async def most_actives(self, top: int):
        return await self._get(f"{DATA}/v1beta1/screener/stocks/most-actives", {"top": min(top, 100), "by": "volume"})

    async def snapshots(self, symbols: list[str]):
        if not symbols:
            return {}
        return await self._get(f"{DATA}/v2/stocks/snapshots", {"symbols": ",".join(symbols)})

    async def intraday_bars(self, symbols: list[str], minutes: int = 240):
        if not symbols:
            return {}
        start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        payload = await self._get(f"{DATA}/v2/stocks/bars", {
            "symbols": ",".join(symbols), "timeframe": "1Min",
            "start": start.isoformat().replace("+00:00", "Z"), "limit": 10000,
            "adjustment": "raw",
        })
        return payload.get("bars", {})

    async def market_regime(self):
        """Simple SPY/QQQ intraday regime filter. Longs are allowed only when the broad tape is healthy."""
        bars = await self.intraday_bars(["SPY", "QQQ"], minutes=180)
        details = {}
        positive = 0
        for symbol in ("SPY", "QQQ"):
            rows = bars.get(symbol, [])
            closes = [float(b.get("c") or 0) for b in rows if float(b.get("c") or 0) > 0]
            if len(closes) < 20:
                details[symbol] = {"healthy": False, "reason": "insufficient_data"}
                continue
            def ema(vals, n):
                k = 2 / (n + 1); out = vals[0]
                for v in vals[1:]: out = v * k + out * (1-k)
                return out
            e9, e20 = ema(closes[-60:], 9), ema(closes[-80:], 20)
            last = closes[-1]
            ret15 = (last / closes[-16] - 1) * 100 if len(closes) >= 16 else 0
            healthy = last > e20 and e9 >= e20 and ret15 > -0.35
            positive += int(healthy)
            details[symbol] = {"price": round(last,4), "ema9": round(e9,4), "ema20": round(e20,4), "ret15_pct": round(ret15,2), "healthy": healthy}
        allowed = positive >= 1
        return {"longs_allowed": allowed, "healthy_indexes": positive, "details": details}

    async def account(self): return await self._get(f"{PAPER}/v2/account")
    async def positions(self): return await self._get(f"{PAPER}/v2/positions")
    async def clock(self): return await self._get(f"{PAPER}/v2/clock")

    async def submit_order(self, payload: dict):
        if not settings.paper: raise RuntimeError("Live trading is disabled in this MVP.")
        if not settings.enable_orders: raise RuntimeError("Order submission disabled. Set ENABLE_PAPER_ORDERS=true.")
        return await self._post(f"{PAPER}/v2/orders", payload)

alpaca = Alpaca()
