import os
import time
import yaml
import ccxt

print("=== PRO BINANCE BOT STARTED V3 ===", flush=True)

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

exchange = ccxt.binance({
    "apiKey": os.getenv("BINANCE_API_KEY"),
    "secret": os.getenv("BINANCE_SECRET"),
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {"defaultType": "future"},
})

timeframe = config["timeframe"]
loop_seconds = config["loop_seconds"]
max_positions = config["max_positions"]

positions = {}


def safe_fetch_tickers(retries=3):
    for i in range(retries):
        try:
            print(f"[TICKERS] Fetching all tickers... try {i+1}", flush=True)
            tickers = exchange.fetch_tickers()
            print(f"[TICKERS] Done. Count={len(tickers)}", flush=True)
            return tickers
        except Exception as e:
            print(f"[TICKERS ERROR] try {i+1}: {e}", flush=True)
            time.sleep(3)
    return {}


def get_symbols():
    print("[1] Loading markets...", flush=True)
    markets = exchange.load_markets()
    print(f"[1] Markets loaded. Count={len(markets)}", flush=True)

    tickers = safe_fetch_tickers()
    symbols = []

    print("[2] Filtering symbols...", flush=True)
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

    symbols = symbols[:40]
    print(f"[2] Symbols selected: {len(symbols)}", flush=True)
    return symbols


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
        print(f"[LEV] {symbol} leverage set", flush=True)
    except Exception as e:
        print(f"[LEV WARN] {symbol}: {e}", flush=True)


def sync_positions_from_exchange():
    global positions

    try:
        fetched = exchange.fetch_positions()
        live_positions = {}

        for p in fetched:
            try:
                symbol = p.get("symbol")
                contracts = float(p.get("contracts") or 0)

                if contracts > 0:
                    side = p.get("side")
                    entry = float(p.get("entryPrice") or 0)
                    unrealized = float(p.get("unrealizedPnl") or 0)

                    live_positions[symbol] = {
                        "side": "buy" if side == "long" else "sell",
                        "entry": entry,
                        "amount": contracts,
                        "unrealized": unrealized,
                        "tp": positions.get(symbol, {}).get("tp"),
                        "sl": positions.get(symbol, {}).get("sl"),
                    }
            except Exception:
                pass

        positions = live_positions
        print(f"[SYNC] Open positions from Binance: {len(positions)}", flush=True)

    except Exception as e:
        print(f"[SYNC ERROR] {e}", flush=True)


def open_trade(symbol, side):
    if symbol in positions:
        print(f"[SKIP] Already open: {symbol}", flush=True)
        return

    if len(positions) >= max_positions:
        print(f"[SKIP] Max positions reached ({max_positions})", flush=True)
        return

    try:
        set_leverage(symbol)
        amount = calculate_amount(symbol)

        print(f"[ENTRY] {side} {symbol} amount={amount}", flush=True)

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

        print(f"[OPENED] {side} {symbol} @ {price} | TP={tp} SL={sl}", flush=True)

    except Exception as e:
        print(f"[OPEN ERROR] {symbol}: {e}", flush=True)


def close_trade(symbol):
    global positions

    pos = positions[symbol]

    try:
        exit_side = "sell" if pos["side"] == "buy" else "buy"

        exchange.create_market_order(
            symbol=symbol,
            side=exit_side,
            amount=pos["amount"],
            params={"reduceOnly": True}
        )

        print(f"[CLOSED] {symbol}", flush=True)
        del positions[symbol]

    except Exception as e:
        print(f"[CLOSE ERROR] {symbol}: {e}", flush=True)


def check_close(symbol):
    pos = positions[symbol]
    price = exchange.fetch_ticker(symbol)["last"]

    tp = pos.get("tp")
    sl = pos.get("sl")

    if tp is None or sl is None:
        return

    if pos["side"] == "buy":
        if price >= tp:
            print(f"[TP HIT] {symbol} price={price}", flush=True)
            close_trade(symbol)
        elif price <= sl:
            print(f"[SL HIT] {symbol} price={price}", flush=True)
            close_trade(symbol)

    if pos["side"] == "sell":
        if price <= tp:
            print(f"[TP HIT] {symbol} price={price}", flush=True)
            close_trade(symbol)
        elif price >= sl:
            print(f"[SL HIT] {symbol} price={price}", flush=True)
            close_trade(symbol)


print("[BOOT] Loading symbols...", flush=True)
symbols = get_symbols()
print(f"[BOOT] Loaded {len(symbols)} symbols", flush=True)

while True:
    try:
        sync_positions_from_exchange()

        print("[LOOP] Scanning...", flush=True)

        for symbol in symbols:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
                signal = get_signal(ohlcv)

                if signal:
                    print(f"[SIGNAL] {signal} on {symbol}", flush=True)
                    open_trade(symbol, signal)

                time.sleep(0.2)

            except Exception as e:
                print(f"[ERR] {symbol}: {e}", flush=True)

        for symbol in list(positions.keys()):
            try:
                check_close(symbol)
            except Exception as e:
                print(f"[CHECK CLOSE ERR] {symbol}: {e}", flush=True)

        print(f"[LOOP] Sleeping {loop_seconds}s", flush=True)
        time.sleep(loop_seconds)

    except Exception as e:
        print(f"[FATAL] {e}", flush=True)
        time.sleep(10)
