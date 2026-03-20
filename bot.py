import time
import yaml
import ccxt

# تحميل الإعدادات
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

mode = config.get("mode", "paper")
loop_seconds = config.get("loop_seconds", 60)
symbols_config = config.get("symbols", [])

print(f"Bot started | mode={mode}")
print("Loading config...")

# إعداد Binance Futures
exchange = ccxt.binanceusdm({
    "enableRateLimit": True
})

def fetch_data(symbol, timeframe, limit):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return ohlcv
    except Exception as e:
        print(f"[ERROR] {symbol}: {e}")
        return None

# بداية التشغيل
while True:
    print("\n==============================")
    print("Bot running... checking market")
    print("==============================")

    for s in symbols_config:
        symbol = s["symbol"]
        timeframe = s["timeframe"]
        limit = s["limit"]

        print(f"Checking {symbol} ({timeframe})")

        data = fetch_data(symbol, timeframe, limit)

        if data:
            last_candle = data[-1]
            close_price = last_candle[4]

            print(f"{symbol} price: {close_price}")

        else:
            print(f"Failed to fetch {symbol}")

    print(f"Sleeping {loop_seconds} seconds...\n")
    time.sleep(loop_seconds)
