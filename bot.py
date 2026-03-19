import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
import json
import os
import yaml
import ccxt.async_support as ccxt
import requests

def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    gain = up.ewm(alpha=1/period, adjust=False).mean()
    loss = down.ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    _atr = atr(df, period)
    hl2 = (df['high'] + df['low']) / 2.0
    upperband = hl2 + multiplier * _atr
    lowerband = hl2 - multiplier * _atr

    final_upperband = upperband.copy()
    final_lowerband = lowerband.copy()
    st = pd.Series(index=df.index, dtype='float64')
    direction = pd.Series(index=df.index, dtype='int64')

    for i in range(1, len(df)):
        if upperband.iloc[i] < final_upperband.iloc[i-1] or df['close'].iloc[i-1] > final_upperband.iloc[i-1]:
            final_upperband.iloc[i] = upperband.iloc[i]
        else:
            final_upperband.iloc[i] = final_upperband.iloc[i-1]

        if lowerband.iloc[i] > final_lowerband.iloc[i-1] or df['close'].iloc[i-1] < final_lowerband.iloc[i-1]:
            final_lowerband.iloc[i] = lowerband.iloc[i]
        else:
            final_lowerband.iloc[i] = final_lowerband.iloc[i-1]

        if pd.isna(st.iloc[i-1]):
            st.iloc[i-1] = final_upperband.iloc[i-1]
            direction.iloc[i-1] = -1

        if st.iloc[i-1] == final_upperband.iloc[i-1]:
            if df['close'].iloc[i] <= final_upperband.iloc[i]:
                st.iloc[i] = final_upperband.iloc[i]
                direction.iloc[i] = -1
            else:
                st.iloc[i] = final_lowerband.iloc[i]
                direction.iloc[i] = 1
        else:
            if df['close'].iloc[i] >= final_lowerband.iloc[i]:
                st.iloc[i] = final_lowerband.iloc[i]
                direction.iloc[i] = 1
            else:
                st.iloc[i] = final_upperband.iloc[i]
                direction.iloc[i] = -1

    result = df.copy()
    result['supertrend'] = st
    result['st_dir'] = direction.fillna(0).astype(int)
    return result

def apply_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['ema_fast'] = ema(out['close'], 9)
    out['ema_slow'] = ema(out['close'], 21)
    out['rsi'] = rsi(out['close'], 14)
    out['atr'] = atr(out, 14)
    st = supertrend(out, 10, 3.0)
    out['supertrend'] = st['supertrend']
    out['st_dir'] = st['st_dir']
    return out

@dataclass
class BotConfig:
    mode: str = "paper"
    loop_seconds: int = 60
    risk_per_trade: float = 0.01
    max_positions: int = 5
    starting_balance_usd: float = 10000.0
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    crypto_provider: str = "binanceusdm"
    symbols: List[Dict[str, Any]] = field(default_factory=list)

def load_config(path: str) -> BotConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw["telegram_token"] = os.getenv("TELEGRAM_TOKEN", raw.get("telegram_token"))
    raw["telegram_chat_id"] = os.getenv("TELEGRAM_CHAT_ID", raw.get("telegram_chat_id"))
    return BotConfig(**raw)

class TelegramAlerter:
    def __init__(self, token: Optional[str], chat_id: Optional[str]):
        self.token = token
        self.chat_id = chat_id

    def send(self, text: str):
        print(text)
        if not self.token or not self.chat_id:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=10,
            )
        except Exception as e:
            print(f"Telegram error: {e}")

@dataclass
class Position:
    symbol: str
    side: str
    entry: float
    qty: float
    stop_loss: float
    take_profit: float
    opened_at: float = field(default_factory=time.time)

class PaperBroker:
    def __init__(self, starting_balance: float):
        self.balance = starting_balance
        self.positions: Dict[str, Position] = {}
        self.history: List[Dict[str, Any]] = []

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def open_position(self, pos: Position):
        self.positions[pos.symbol] = pos

    def close_position(self, symbol: str, price: float, reason: str):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None
        mult = 1 if pos.side == "long" else -1
        pnl = (price - pos.entry) * pos.qty * mult
        self.balance += pnl
        rec = {
            "symbol": symbol,
            "side": pos.side,
            "entry": pos.entry,
            "exit": price,
            "qty": pos.qty,
            "pnl": pnl,
            "reason": reason,
            "opened_at": pos.opened_at,
            "closed_at": time.time(),
            "balance": self.balance,
        }
        self.history.append(rec)
        return rec

class CCXTProvider:
    def __init__(self, exchange_id: str, api_key=None, secret=None):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            "apiKey": api_key or "",
            "secret": secret or "",
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

    async def fetch_ohlcv(self, symbol_cfg: Dict[str, Any]) -> pd.DataFrame:
        rows = await self.exchange.fetch_ohlcv(
            symbol_cfg["symbol"],
            timeframe=symbol_cfg.get("timeframe", "4h"),
            limit=symbol_cfg.get("limit", 250),
        )
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    async def place_market_order(self, symbol: str, side: str, amount: float):
        return await self.exchange.create_order(symbol, "market", side, amount)

    async def place_stop_market(self, symbol: str, side: str, amount: float, stop_price: float):
        return await self.exchange.create_order(
            symbol, "STOP_MARKET", side, amount, None,
            {"stopPrice": stop_price, "reduceOnly": True}
        )

    async def place_take_profit_market(self, symbol: str, side: str, amount: float, trigger_price: float):
        return await self.exchange.create_order(
            symbol, "TAKE_PROFIT_MARKET", side, amount, None,
            {"stopPrice": trigger_price, "reduceOnly": True}
        )

    async def close(self):
        await self.exchange.close()

class TrendBreakoutStrategy:
    def __init__(self, lookback_breakout: int = 20, atr_stop_mult: float = 1.8, rr: float = 2.0):
        self.lookback_breakout = lookback_breakout
        self.atr_stop_mult = atr_stop_mult
        self.rr = rr

    def generate(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        if len(df) < max(50, self.lookback_breakout + 5):
            return None
        last = df.iloc[-1]
        last_high_n = df['high'].iloc[-self.lookback_breakout-1:-1].max()
        last_low_n = df['low'].iloc[-self.lookback_breakout-1:-1].min()

        if (
            last['close'] > last['supertrend']
            and last['ema_fast'] > last['ema_slow']
            and 52 <= last['rsi'] <= 78
            and last['close'] > last_high_n
        ):
            stop = last['close'] - self.atr_stop_mult * last['atr']
            tp = last['close'] + self.rr * (last['close'] - stop)
            return {"signal": "long", "entry": float(last['close']), "stop": float(stop), "tp": float(tp)}

        if (
            last['close'] < last['supertrend']
            and last['ema_fast'] < last['ema_slow']
            and 22 <= last['rsi'] <= 48
            and last['close'] < last_low_n
        ):
            stop = last['close'] + self.atr_stop_mult * last['atr']
            tp = last['close'] - self.rr * (stop - last['close'])
            return {"signal": "short", "entry": float(last['close']), "stop": float(stop), "tp": float(tp)}

        return None

class TradingBot:
    def __init__(self, config: BotConfig):
        self.cfg = config
        self.alerter = TelegramAlerter(config.telegram_token, config.telegram_chat_id)
        self.paper = PaperBroker(config.starting_balance_usd)
        self.strategy = TrendBreakoutStrategy()
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        self.provider = CCXTProvider(config.crypto_provider, api_key=api_key, secret=api_secret)

    def risk_qty(self, entry: float, stop: float) -> float:
        risk_usd = self.paper.balance * self.cfg.risk_per_trade
        stop_distance = abs(entry - stop)
        if stop_distance <= 0:
            return 0
        return max(risk_usd / stop_distance, 0)

    async def process_symbol(self, symbol_cfg: Dict[str, Any]):
        symbol = symbol_cfg["symbol"]
        df = await self.provider.fetch_ohlcv(symbol_cfg)
        df = apply_indicators(df)
        last = df.iloc[-1]

        if self.paper.has_position(symbol):
            pos = self.paper.positions[symbol]
            if pos.side == "long":
                if last["low"] <= pos.stop_loss:
                    rec = self.paper.close_position(symbol, pos.stop_loss, "stop_loss")
                    self.alerter.send(f"[PAPER EXIT] STOP {symbol} pnl={rec['pnl']:.2f} balance={rec['balance']:.2f}")
                    return
                if last["high"] >= pos.take_profit:
                    rec = self.paper.close_position(symbol, pos.take_profit, "take_profit")
                    self.alerter.send(f"[PAPER EXIT] TP {symbol} pnl={rec['pnl']:.2f} balance={rec['balance']:.2f}")
                    return
            if pos.side == "short":
                if last["high"] >= pos.stop_loss:
                    rec = self.paper.close_position(symbol, pos.stop_loss, "stop_loss")
                    self.alerter.send(f"[PAPER EXIT] STOP {symbol} pnl={rec['pnl']:.2f} balance={rec['balance']:.2f}")
                    return
                if last["low"] <= pos.take_profit:
                    rec = self.paper.close_position(symbol, pos.take_profit, "take_profit")
                    self.alerter.send(f"[PAPER EXIT] TP {symbol} pnl={rec['pnl']:.2f} balance={rec['balance']:.2f}")
                    return
            return

        if len(self.paper.positions) >= self.cfg.max_positions:
            return

        sig = self.strategy.generate(df)
        if not sig:
            return

        qty = self.risk_qty(sig["entry"], sig["stop"])
        if qty <= 0:
            return

        if self.cfg.mode == "paper":
            self.paper.open_position(Position(symbol, sig["signal"], sig["entry"], qty, sig["stop"], sig["tp"]))
            self.alerter.send(
                f"[PAPER ENTRY] {symbol} {sig['signal']} entry={sig['entry']:.6f} sl={sig['stop']:.6f} tp={sig['tp']:.6f} qty={qty:.6f}"
            )
        else:
            side = "buy" if sig["signal"] == "long" else "sell"
            exit_side = "sell" if side == "buy" else "buy"
            await self.provider.place_market_order(symbol, side, qty)
            await self.provider.place_stop_market(symbol, exit_side, qty, sig["stop"])
            await self.provider.place_take_profit_market(symbol, exit_side, qty, sig["tp"])
            self.alerter.send(
                f"[LIVE ENTRY] {symbol} {sig['signal']} entry≈{sig['entry']:.6f} sl={sig['stop']:.6f} tp={sig['tp']:.6f} qty={qty:.6f}"
            )

    async def run_once(self):
        for sym in self.cfg.symbols:
            try:
                await self.process_symbol(sym)
            except Exception as e:
                self.alerter.send(f"[ERROR] {sym.get('symbol')}: {e}")

    async def run_forever(self):
        self.alerter.send(f"Bot started | mode={self.cfg.mode}")
        while True:
            await self.run_once()
            await asyncio.sleep(self.cfg.loop_seconds)

    async def close(self):
        await self.provider.close()

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    bot = TradingBot(cfg)
    try:
        if args.once:
            await bot.run_once()
            print(json.dumps({
                "balance": bot.paper.balance,
                "positions": {k: vars(v) for k, v in bot.paper.positions.items()},
                "history": bot.paper.history[-10:]
            }, indent=2, default=str))
        else:
            await bot.run_forever()
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
