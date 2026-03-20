import time
import yaml
import ccxt
import traceback

print("=== PAPER ENTRY VERSION ===")

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

mode = config.get("mode", "paper")
loop_seconds = config.get("loop_seconds", 60)
symbols_config = config.get("symbols", [])
starting_balance = float(config.get("starting_balance_usd", 10000))
risk_per_trade = float(config.get("risk_per_trade", 0.01))
max_positions = int(config.get("max_positions", 3))

print(f"Bot started | mode={mode}")
print(f"Loop seconds: {loop_seconds}")
print(f"Symbols loaded: {symbols_config}")

exchange = ccxt.binanceusdm({
    "enableRateLimit": True,
})

balance = starting_balance
positions = {}

def fetch_data(symbol, timeframe, limit, retries=3):
    for attempt in range(retries):
        try:
            print(f"Fetching {symbol} | tf={timeframe} | limit={limit} | try={attempt+1}")
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            print(f"Fetched candles for {symbol}: {len(ohlcv)}")
            return ohlcv
        except Exception as e:
            print(f"[ERROR] {symbol} try {attempt+1}: {e}")
            time.sleep(2)
    print(f"Failed to fetch {symbol} after {retries} tries")
    return None

def calc_qty(entry_price, stop_price):
    risk_amount = balance * risk_per_trade
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return 0
    return risk_amount / stop_distance

def open_long(symbol, price):
    global positions

    sl = price * 0.995
    tp = price * 1.01
    qty = calc_qty(price, sl)

    if qty <= 0:
        print(f"[SKIP] Invalid qty for {symbol}")
        return

    positions[symbol] = {
        "side": "long",
        "entry": price,
        "sl": sl,
        "tp": tp,
        "qty": qty,
    }

    print(f"[PAPER ENTRY][LONG] {symbol}")
    print(f"Entry: {price:.6f} | SL: {sl:.6f} | TP: {tp:.6f} | QTY: {qty:.6f}")

def check_exit(symbol, price):
    global balance, positions

    if symbol not in positions:
        return

    pos = positions[symbol]
    entry = pos["entry"]
    sl = pos["sl"]
    tp = pos["tp"]
    qty = pos["qty"]

    if price <= sl:
        pnl = (sl - entry) * qty
        balance += pnl
        print(f"[PAPER EXIT][SL] {symbol} | Exit: {sl:.6f} | PnL: {pnl:.2f} | Balance: {balance:.2f}")
        del positions[symbol]
        return

    if price >= tp:
        pnl = (tp - entry) * qty
        balance += pnl
        print(f"[PAPER EXIT][TP] {symbol} | Exit: {tp:.6f} | PnL: {pnl:.2f} | Balance: {balance:.2f}")
        del positions[symbol]
        return

while True:
    try:
        print("\n===================================")
        print("Bot running... checking market")
        print(f"Balance: {balance:.2f} | Open positions: {len(positions)}")
        print("===================================")

        for s in symbols_config:
            symbol = s["symbol"]
            timeframe = s.get("timeframe", "1h")
            limit = s.get("limit", 100)

            print(f"Checking {symbol}")
            data = fetch_data(symbol, timeframe, limit)

            if not data:
                continue

            closes = [x[4] for x in data]
            price = closes[-1]

            print(f"{symbol} price: {price}")

            check_exit(symbol, price)

            if symbol not in positions and len(positions) < max_positions:
                open_long(symbol, price)

        if positions:
            print("\nOpen positions:")
            for sym, pos in positions.items():
                print(
                    f" - {sym} | {pos['side']} | "
                    f"entry={pos['entry']:.6f} | sl={pos['sl']:.6f} | tp={pos['tp']:.6f} | qty={pos['qty']:.6f}"
                )
        else:
            print("\nNo open positions")

        print(f"\nSleeping {loop_seconds} seconds...\n")
        time.sleep(loop_seconds)

    except Exception as e:
        print(f"[FATAL ERROR] {e}")
        traceback.print_exc()
        time.sleep(15)
