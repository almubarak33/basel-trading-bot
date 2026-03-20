import os
import time
import yaml
import ccxt

# تحميل الإعدادات
with open("config.yaml") as f:
    config = yaml.safe_load(f)

exchange = ccxt.okx({
    "apiKey": os.getenv("OKX_API_KEY"),
    "secret": os.getenv("OKX_SECRET"),
    "password": os.getenv("OKX_PASSPHRASE"),
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
})

timeframe = config["timeframe"]
loop_seconds = config["loop_seconds"]
risk_usd = config["risk_per_trade_usd"]
max_positions = config["max_positions"]

open_positions = set()

# -----------------------------
# جلب جميع العملات القوية
# -----------------------------
def get_symbols():
    markets = exchange.load_markets()
    symbols = []

    for s in markets:
        m = markets[s]

        if (
            m["active"]
            and m["swap"]
            and m["quote"] == "USDT"
        ):
            try:
                ticker = exchange.fetch_ticker(s)
                volume = ticker.get("quoteVolume", 0)

                if volume and volume > config["filters"]["min_volume"]:
                    symbols.append(s)

            except:
                pass

    return symbols

# -----------------------------
# إشارة التداول (احترافية)
# -----------------------------
def get_signal(ohlcv):
    closes = [c[4] for c in ohlcv]

    if len(closes) < 50:
        return None

    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50

    last = closes[-1]

    # ترند + زخم
    if last > ma20 and ma20 > ma50:
        return "buy"

    if last < ma20 and ma20 < ma50:
        return "sell"

    return None

# -----------------------------
# حساب الكمية
# -----------------------------
def get_amount(symbol):
    ticker = exchange.fetch_ticker(symbol)
    price = ticker["last"]

    amount = risk_usd / price
    amount = float(exchange.amount_to_precision(symbol, amount))

    return amount

# -----------------------------
# تنفيذ الصفقة
# -----------------------------
def place_trade(symbol, side):
    if symbol in open_positions:
        return

    if len(open_positions) >= max_positions:
        return

    try:
        amount = get_amount(symbol)

        order = exchange.create_market_order(
            symbol=symbol,
            side=side,
            amount=amount
        )

        open_positions.add(symbol)

        print(f"🔥 TRADE {side} {symbol}")

    except Exception as e:
        print(f"ERROR {symbol}: {e}")

# -----------------------------
# التشغيل
# -----------------------------
symbols = get_symbols()
print(f"Loaded {len(symbols)} symbols")

while True:
    try:
        print("Scanning...")

        for symbol in symbols:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)

                signal = get_signal(ohlcv)

                if signal:
                    place_trade(symbol, signal)

            except Exception as e:
                print(f"ERR {symbol}: {e}")

        time.sleep(loop_seconds)

    except Exception as e:
        print("FATAL:", e)
        time.sleep(5)
