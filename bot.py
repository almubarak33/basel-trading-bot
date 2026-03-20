import os
import time
import yaml
import ccxt

with open("config.yaml") as f:
    config = yaml.safe_load(f)

exchange = ccxt.okx({
    "apiKey": os.getenv("OKX_API_KEY"),
    "secret": os.getenv("OKX_SECRET"),
    "password": os.getenv("OKX_PASSPHRASE"),
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
})

symbols = ["BTC/USDT:USDT"]

def get_signal(ohlcv):
    closes = [c[4] for c in ohlcv]

    if len(closes) < 50:
        return None

    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50

    if closes[-1] > ma20 and ma20 > ma50:
        return "buy"

    if closes[-1] < ma20 and ma20 < ma50:
        return "sell"

    return None


def calculate_contracts(symbol):
    market = exchange.market(symbol)

    # 🔥 الحد الأدنى للعقود
    min_contracts = market["limits"]["amount"]["min"] or 1

    # نخليه دائمًا رقم صحيح
    contracts = max(1, int(min_contracts))

    return contracts


def place_trade(symbol, side):
    try:
        contracts = calculate_contracts(symbol)

        print(f"Placing {side} {symbol} contracts={contracts}")

        order = exchange.create_market_order(
            symbol=symbol,
            side=side,
            amount=contracts
        )

        print("DONE:", order)

    except Exception as e:
        print("ERROR:", e)


while True:
    try:
        print("Scanning...")

        for symbol in symbols:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=config["timeframe"], limit=100)

            signal = get_signal(ohlcv)

            if signal:
                place_trade(symbol, signal)

        time.sleep(config["loop_seconds"])

    except Exception as e:
        print("FATAL:", e)
        time.sleep(5)
