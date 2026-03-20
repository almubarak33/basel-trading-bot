import os
import time
import yaml
import ccxt
from datetime import datetime, timedelta

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

open_positions = {}
cooldowns = {}

# -----------------------------
# جلب العملات
# -----------------------------
def get_symbols():
    markets = exchange.load_markets()
    symbols = []

    for s in markets:
        m = markets[s]

        if m["active"] and m["swap"] and m["quote"] == "USDT":
            try:
                ticker = exchange.fetch_ticker(s)
                vol = ticker.get("quoteVolume", 0)

                if vol and vol > config["filters"]["min_volume"]:
                    symbols.append(s)

            except:
                pass

    return symbols

# -----------------------------
# إشارة التداول
# -----------------------------
def get_signal(ohlcv):
    closes = [c[4] for c in ohlcv]

    if len(closes) < 50:
        return None

    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50

    price = closes[-1]

    if price > ma20 and ma20 > ma50:
        return "buy"

    if price < ma20 and ma20 < ma50:
        return "sell"

    return None

# -----------------------------
# حساب الكمية
# -----------------------------
def get_amount(symbol):
    ticker = exchange.fetch_ticker(symbol)
    price = ticker["last"]

    amount = config["risk_per_trade_usd"] / price
    amount = float(exchange.amount_to_precision(symbol, amount))

    return amount, price

# -----------------------------
# تنفيذ الصفقة
# -----------------------------
def place_trade(symbol, side):
    if symbol in open_positions:
        return

    if len(open_positions) >= config["max_positions"]:
        return

    if symbol in cooldowns and cooldowns[symbol] > datetime.now():
        return

    try:
        amount, price = get_amount(symbol)

        order = exchange.create_market_order(symbol, side, amount)

        # SL / TP
        sl_pct = config["risk"]["sl_pct"]
        tp_pct = config["risk"]["tp_pct"]

        if side == "buy":
            sl = price * (1 - sl_pct)
            tp = price * (1 + tp_pct)
            exit_side = "sell"
        else:
            sl = price * (1 + sl_pct)
            tp = price * (1 - tp_pct)
            exit_side = "buy"

        exchange.create_order(symbol, "STOP_MARKET", exit_side, amount, None, {"stopPrice": sl})
        exchange.create_order(symbol, "TAKE_PROFIT_MARKET", exit_side, amount, None, {"stopPrice": tp})

        open_positions[symbol] = True
        cooldowns[symbol] = datetime.now() + timedelta(minutes=config["cooldown_minutes"])

        print(f"🔥 {side.upper()} {symbol} | SL:{sl} TP:{tp}")

    except Exception as e:
        print(f"ERROR {symbol}: {e}")

# -----------------------------
# إغلاق كل الصفقات
# -----------------------------
def close_all():
    for symbol in open_positions:
        try:
            exchange.create_market_order(symbol, "sell", 1)
        except:
            pass

# -----------------------------
# التشغيل
# -----------------------------
symbols = get_symbols()
print(f"Loaded {len(symbols)} symbols")

while True:
    try:
        if config["emergency_close_all"]:
            close_all()
            print("🚨 ALL CLOSED")

        if not config["enabled"]:
            print("⏸ BOT PAUSED")
            time.sleep(loop_seconds)
            continue

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
