import ccxt
import time
import os
import yaml

with open("config.yaml") as f:
    config = yaml.safe_load(f)

exchange = ccxt.okx({
    'apiKey': os.getenv("OKX_API_KEY"),
    'secret': os.getenv("OKX_SECRET"),
    'password': os.getenv("OKX_PASSPHRASE"),
    'enableRateLimit': True,
})

symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

def get_signal(data):
    closes = [c[4] for c in data]
    if len(closes) < 50:
        return None

    if closes[-1] > sum(closes[-20:])/20:
        return "buy"
    elif closes[-1] < sum(closes[-20:])/20:
        return "sell"

    return None

while True:
    try:
        print("Scanning...")

        for symbol in symbols:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=config["timeframe"], limit=100)
            signal = get_signal(ohlcv)

            if signal:
                print(f"Signal {signal} on {symbol}")

                amount = config["risk_per_trade_usd"] / ohlcv[-1][4]

                order = exchange.create_market_order(symbol, signal, amount)

                print("ORDER EXECUTED:", order)

        time.sleep(config["loop_seconds"])

    except Exception as e:
        print("ERROR:", e)
        time.sleep(5)
