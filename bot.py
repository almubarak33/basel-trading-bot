import time
import yaml
import ccxt

print("=== NEW BOT VERSION ===")

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

exchange = ccxt.binanceusdm()

balance = 10000
positions = {}

while True:
    print("\n=== RUNNING ===")

    symbols = ["BTC/USDT:USDT"]

    for symbol in symbols:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1h", limit=50)
            price = ohlcv[-1][4]

            print(f"{symbol} price: {price}")

            if symbol not in positions:
                print(f"[FORCE ENTRY] {symbol}")

                entry = price
                sl = price * 0.995
                tp = price * 1.01

                qty = 1

                positions[symbol] = {
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "qty": qty
                }

            else:
                pos = positions[symbol]

                if price <= pos["sl"]:
                    print(f"[SL HIT] {symbol}")
                    del positions[symbol]

                elif price >= pos["tp"]:
                    print(f"[TP HIT] {symbol}")
                    del positions[symbol]

        except Exception as e:
            print(f"Error: {e}")

    time.sleep(10)
