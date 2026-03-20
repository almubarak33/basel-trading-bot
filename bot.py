import time
import ccxt

print("=== NEW BOT VERSION ===")

exchange = ccxt.binanceusdm()

positions = {}

while True:
    print("\n=== RUNNING ===")

    symbol = "BTC/USDT:USDT"

    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1h", limit=50)
        price = ohlcv[-1][4]

        print(f"{symbol} price: {price}")

        if symbol not in positions:
            print(f"[FORCE ENTRY] {symbol}")

            entry = price
            sl = price * 0.995
            tp = price * 1.01

            positions[symbol] = {
                "entry": entry,
                "sl": sl,
                "tp": tp
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
        print("Error:", e)

    time.sleep(10)
