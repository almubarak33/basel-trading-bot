import os
import time
import yaml
import ccxt

print("=== PRO BINANCE BOT STARTED V2 ===", flush=True)

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

exchange = ccxt.binance({
    "apiKey": os.getenv("BINANCE_API_KEY"),
    "secret": os.getenv("BINANCE_SECRET"),
    "enableRateLimit": True,
    "options": {"defaultType": "future"},
})

timeframe = config["timeframe"]
loop_seconds = config["loop_seconds"]
max_positions = config["max_positions"]

positions = {}


def safe_fetch_tickers(retries=3):
    for i in range(retries):
        try:
            return exchange.fetch_tickers()
        except Exception as e:
            print(f"[TICKERS ERROR] try {i+1}: {e}", flush=True)
            time.sleep(3)
    return {}


def get_symbols():
    markets = exchange.load_markets()
    tickers = safe_fetch_tickers()
    symbols = []

    for s, m in markets.items():
        try:
            if not m.get("active", True):
                continue
            if not m.get("contract", False):
                continue
            if m.get("quote") != "USDT":
                continue

            ticker = tickers.get(s)
            if not ticker:
                continue

            vol = ticker.get("quoteVolume", 0) or 0
            if vol > config["filters"]["min_volume"]:
                symbols.append(s)

        except Exception:
            pass

    # نقلل العدد عشان ما نضغط المنصة
    return symbols[:40]


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


def calculate_amount(symbol):
    risk = config["risk_per_trade"]
    price = exchange.fetch_ticker(symbol)["last"]
    amount = risk / price
    return float(exchange.amount_to_precision(symbol, amount))


def set_leverage(symbol):
    try:
        exchange.set_leverage(config["leverage"], symbol)
    except Exception as e:
        print(f"[LEV WARN] {symbol}: {e}", flush=True)


def open_trade(symbol, side):
    if symbol in positions:
        return

    if len(positions) >= max_positions:
        return

    try:
        set_leverage(symbol)
        amount = calculate_amount(symbol)

        order = exchange.create_market_order(
            symbol=symbol,
            side=side,
            amount=amount
        )

        price = exchange.fetch_ticker(symbol)["last"]

        tp = price * (1 + config["tp_percent"] / 100) if side == "buy" else price * (1 - config["tp_percent"] / 100)
        sl = price * (1 - config["sl_percent"] / 100) if side == "buy" else price * (1 + config["sl_percent"] / 100)

        positions[symbol] = {
            "side": side,
            "entry": price,
            "tp": tp,
            "sl": sl,
            "amount": amount
        }

        print(f"OPEN {side} {symbol} @ {price}", flush=True)

    except Exception as e:
        print(f"OPEN ERROR {symbol}: {e}", flush=True)


def close_trade(symbol):
    pos = positions[symbol]

    try:
        exit_side = "sell" if pos["side"] == "buy" else "buy"

        exchange.create_market_order(
            symbol=symbol,
            side=exit_side,
            amount=pos["amount"],
            params={"reduceOnly": True}
        )

        print(f"CLOSE {symbol}", flush=True)
        del positions[symbol]

    except Exception as e:
        print(f"CLOSE ERROR {symbol}: {e}", flush=True)


def check_close(symbol):
    pos = positions[symbol]
    price = exchange.fetch_ticker(symbol)["last"]

    if pos["side"] == "buy":
        if price >= pos["tp"] or price <= pos["sl"]:
            close_trade(symbol)

    if pos["side"] == "sell":
        if price <= pos["tp"] or price >= pos["sl"]:
            close_trade(symbol)


while True:
    try:
        print("Loading symbols...", flush=True)
        symbols = get_symbols()
        print(f"Loaded {len(symbols)} symbols", flush=True)

        print("Scanning...", flush=True)

        for symbol in symbols:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
                signal = get_signal(ohlcv)

                if signal:
                    print(f"Signal {signal} on {symbol}", flush=True)
                    open_trade(symbol, signal)

                time.sleep(0.25)  # تخفيف الضغط

            except Exception as e:
                print(f"ERR {symbol}: {e}", flush=True)

        for symbol in list(positions.keys()):
            try:
                check_close(symbol)
            except Exception as e:
                print(f"CHECK CLOSE ERR {symbol}: {e}", flush=True)

        time.sleep(loop_seconds)

    except Exception as e:
        print(f"FATAL {e}", flush=True)
        time.sleep(10)
