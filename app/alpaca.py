from __future__ import annotations
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
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            return r.json()

    async def _post(self, url: str, payload: dict):
        async with httpx.AsyncClient(timeout=12) as c:
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

    async def account(self):
        return await self._get(f"{PAPER}/v2/account")

    async def positions(self):
        return await self._get(f"{PAPER}/v2/positions")

    async def clock(self):
        return await self._get(f"{PAPER}/v2/clock")

    async def submit_order(self, payload: dict):
        if not settings.paper:
            raise RuntimeError("Live trading is disabled in this MVP.")
        if not settings.enable_orders:
            raise RuntimeError("Order submission disabled. Set ENABLE_PAPER_ORDERS=true.")
        return await self._post(f"{PAPER}/v2/orders", payload)

alpaca = Alpaca()
