import os
import time
import math
import yaml
import ccxt

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

exchange = ccxt.okx({
    "apiKey": os.getenv("OKX_API_KEY"),
    "secret": os.getenv("OKX_SECRET"),
    "password": os.getenv("OKX_PASSPHRASE"),
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
    },
})

symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

timeframe = config.get("timeframe", "15m")
loop_seconds = int(config.get("loop_seconds", 30))
risk_per_trade_usd = float(config.get("risk_per_trade_usd", 15))


def sma(values, length):
    if len(values) < length:
        return None
    return sum(values[-length:]) / length


def get_signal(data):
    closes = [c[4] for c in data]
    if len(closes) < 50:
        return None

    ma20 = sma(closes, 20)
    if ma20 is None:
        return None

    last = closes[-1]
    prev = closes[-2]

    if prev <= ma20 and last > ma20:
        return "buy"

    if prev >= ma20 and last < ma20:
        return "sell"

    return None


def get_last_price(symbol):
    ticker = exchange.fetch_ticker(symbol)
    return float(ticker["last"])


def get_market_limits(symbol):
    market = exchange.market(symbol)
    limits = market.get("limits", {})
    amount_limits = limits.get("amount", {}) or {}
    min_amount = amount_limits.get("min") or 0.0

    precision = market.get("precision", {}) or {}
    amount_precision = precision.get("amount", None)

    return market, float(min_amount), amount_precision


def calculate_contract_amount(symbol, usdt_amount):
    price = get_last_price(symbol)
    market, min_amount, _ = get_market_limits(symbol)

    raw_amount = usdt_amount / price

    # استخدم precision الرسمية من المنصة
    precise_amount_str = exchange.amount_to_precision(symbol, raw_amount)
    precise_amount = float(precise_amount_str)

    # إذا صار أقل من الحد الأدنى، ارفعه للحد الأدنى
    if min_amount and precise_amount < min_amount:
        precise_amount = min_amount
        precise_amount = float(exchange.amount_to_precision(symbol, precise_amount))

    return precise_amount, price


def place_market_order(symbol, side, usdt_amount):
    amount, price = calculate_contract_amount(symbol, usdt_amount)

    if amount <= 0:
        raise Exception(f"invalid amount for {symbol}: {amount}")

    print(f"Placing {side} on {symbol} | usdt={usdt_amount} | amount={amount} | price={price}", flush=True)

    order = exchange.create_order(
        symbol=symbol,
        type="market",
        side=side,
        amount=amount,
        params={}
    )
    return order


while True:
    try:
        print("Scanning...", flush=True)

        for symbol in symbols:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
                signal = get_signal(ohlcv)

                if signal:
                    print(f"Signal {signal} on {symbol}", flush=True)
                    order = place_market_order(symbol, signal, risk_per_trade_usd)
                    print(f"ORDER EXECUTED: {order}", flush=True)
                else:
                    print(f"No signal on {symbol}", flush=True)

            except Exception as e:
                print(f"ERROR on {symbol}: {e}", flush=True)

        time.sleep(loop_seconds)

    except Exception as e:
        print(f"FATAL ERROR: {e}", flush=True)
        time.sleep(5)
