from __future__ import annotations
from datetime import datetime, timedelta, timezone
import httpx
from .config import settings
from .indicators import compute_regime

DATA = "https://data.alpaca.markets"
PAPER = "https://paper-api.alpaca.markets"

STOP_ORDER_TYPES = {"stop", "stop_limit", "trailing_stop"}


def extract_stop_prices(orders: list[dict]) -> dict[str, float]:
    """Map symbol -> working stop price, reading bracket legs as well as top-level orders."""
    stops: dict[str, float] = {}
    def visit(order: dict) -> None:
        for leg in order.get("legs") or []: visit(leg)
        if (order.get("side") or "").lower() != "sell": return
        if (order.get("type") or "").lower() not in STOP_ORDER_TYPES: return
        symbol = (order.get("symbol") or "").upper()
        try: price = float(order.get("stop_price") or 0)
        except (TypeError, ValueError): return
        if symbol and price > 0: stops[symbol] = max(stops.get(symbol, 0.0), price)
    for order in orders or []: visit(order)
    return stops


class Alpaca:
    def __init__(self):
        self.headers = {"APCA-API-KEY-ID": settings.api_key,"APCA-API-SECRET-KEY": settings.api_secret}

    def configured(self) -> bool: return bool(settings.api_key and settings.api_secret)

    async def _get(self,url:str,params=None):
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.get(url,headers=self.headers,params=params); r.raise_for_status(); return r.json()

    async def _post(self,url:str,payload:dict):
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.post(url,headers=self.headers,json=payload); r.raise_for_status(); return r.json()

    async def _delete(self,url:str,params=None):
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.delete(url,headers=self.headers,params=params); r.raise_for_status()
            if not r.content: return {"ok":True}
            try: return r.json()
            except Exception: return {"ok":True,"text":r.text}

    async def movers(self,top:int): return await self._get(f"{DATA}/v1beta1/screener/stocks/movers",{"top":min(top,50)})
    async def most_actives(self,top:int): return await self._get(f"{DATA}/v1beta1/screener/stocks/most-actives",{"top":min(top,100),"by":"volume"})

    async def snapshots(self,symbols:list[str]):
        if not symbols:return {}
        return await self._get(f"{DATA}/v2/stocks/snapshots",{"symbols":",".join(symbols)})

    async def latest_quotes(self,symbols:list[str]):
        if not symbols:return {}
        payload=await self._get(f"{DATA}/v2/stocks/quotes/latest",{"symbols":",".join(symbols)})
        return payload.get("quotes", payload)

    async def latest_trades(self,symbols:list[str]):
        if not symbols:return {}
        payload=await self._get(f"{DATA}/v2/stocks/trades/latest",{"symbols":",".join(symbols)})
        return payload.get("trades", payload)

    async def intraday_bars(self,symbols:list[str],minutes:int=240):
        if not symbols:return {}
        start=datetime.now(timezone.utc)-timedelta(minutes=minutes)
        payload=await self._get(f"{DATA}/v2/stocks/bars",{"symbols":",".join(symbols),"timeframe":"1Min","start":start.isoformat().replace("+00:00","Z"),"limit":10000,"adjustment":"raw"})
        return payload.get("bars",{})

    async def daily_bars(self,symbols:list[str],days:int=25):
        if not symbols:return {}
        start=datetime.now(timezone.utc)-timedelta(days=max(days*2,40))
        payload=await self._get(f"{DATA}/v2/stocks/bars",{"symbols":",".join(symbols),"timeframe":"1Day","start":start.isoformat().replace("+00:00","Z"),"limit":10000,"adjustment":"raw"})
        return payload.get("bars",{})

    async def market_regime(self):
        bars=await self.intraday_bars(["SPY","QQQ"],minutes=180)
        return compute_regime(bars)

    async def account(self): return await self._get(f"{PAPER}/v2/account")
    async def positions(self): return await self._get(f"{PAPER}/v2/positions")
    async def open_orders(self): return await self._get(f"{PAPER}/v2/orders",{"status":"open","nested":"true","limit":500})
    async def clock(self): return await self._get(f"{PAPER}/v2/clock")

    async def risk_status(self):
        account=await self.account(); equity=float(account.get("equity",0) or 0); last_equity=float(account.get("last_equity",equity) or equity)
        dd=((equity/last_equity)-1)*100 if last_equity>0 else 0
        return {"equity":equity,"last_equity":last_equity,"daily_return_pct":round(dd,3),"daily_loss_limit_pct":settings.max_daily_loss*100,"blocked":dd<=-(settings.max_daily_loss*100)}

    async def submit_order(self,payload:dict):
        if not settings.paper: raise RuntimeError("Live trading is disabled in this MVP.")
        if not settings.enable_orders: raise RuntimeError("Order submission disabled. Set ENABLE_PAPER_ORDERS=true.")
        return await self._post(f"{PAPER}/v2/orders",payload)

    async def close_position(self,symbol:str):
        if not settings.paper: raise RuntimeError("Live trading is disabled.")
        if not settings.enable_orders: raise RuntimeError("Paper orders are disabled.")
        return await self._delete(f"{PAPER}/v2/positions/{symbol.upper()}")

    async def close_all_positions(self):
        if not settings.paper: raise RuntimeError("Live trading is disabled.")
        if not settings.enable_orders: raise RuntimeError("Paper orders are disabled.")
        return await self._delete(f"{PAPER}/v2/positions",{"cancel_orders":"true"})

alpaca=Alpaca()
