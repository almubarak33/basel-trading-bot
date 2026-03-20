import time
import yaml
import ccxt
import traceback

print("=== FILE LOADED ===")

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

mode = config.get("mode", "paper")
loop_seconds = config.get("loop_seconds", 60)
symbols_config = config.get("symbols", [])

print(f"Bot started | mode={mode}")
print(f"Loop seconds: {loop_seconds}")
print(f"Symbols loaded: {symbols_config}")

exchange = ccxt.binanceusdm({
    "enableRateLimit": True
})

def fetch_data(symbol, timeframe, limit):
    try:
        print(f"Fetching {symbol} | tf={timeframe} | limit={limit}")
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        print(f"Fetched candles for {symbol}: {len(ohlcv)}")
        return ohlcv
    except Exception as e:
        print(f"[ERROR] fetch_data {symbol}: {e}")
        traceback.print_exc()
        return None

while True:
    try:
        print("===================================")
        print("Bot running... checking market")
        print("===================================")

        for s in symbols_config:
            symbol = s["symbol"]
            timeframe = s.get("timeframe", "1h")
            limit = s.get("limit", 250)

            print(f"Checking {symbol}")
            data = fetch_data(symbol, timeframe, limit)

            if data:
                last_candle = data[-1]
                close_price = last_candle[4]
                print(f"{symbol} price: {close_price}")
            else:
                print(f"Failed to fetch {symbol}")

        print(f"Sleeping {loop_seconds} seconds...")
        time.sleep(loop_seconds)

    except Exception as e:
        print(f"[FATAL ERROR] {e}")
        traceback.print_exc()
        time.sleep(15)
