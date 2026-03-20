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
starting_balance = float(config.get("starting_balance_usd", 10000))
risk_per_trade = float(config.get("risk_per_trade", 0.01))
max_positions = int(config.get("max_positions", 3))

print(f"Bot started | mode={mode}")
print(f"Loop seconds: {loop_seconds}")
print(f"Symbols loaded: {symbols_config}")

exchange = ccxt.binanceusdm({
    "enableRateLimit": True
})

balance = starting_balance
positions = {}

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

def sma(values, length):
    if len(values) < length:
        return None
    return sum(values[-length:]) / length

def calc_qty(entry, stop):
    global balance
    risk_amount = balance * risk_per_trade
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return 0
    return risk_amount / stop_distance

def check_exit(symbol, price):
    global balance
    if symbol not in positions:
        return

    pos = positions[symbol]
    side = pos["side"]
    entry = pos["entry"]
    qty = pos["qty"]
    sl = pos["sl"]
    tp = pos["tp"]

    if side == "long":
        if price <= sl:
            pnl = (sl - entry) * qty
            balance += pnl
            print(f"[PAPER EXIT][SL] {symbol} exit={sl:.6f} pnl={pnl:.2f} balance={balance:.2f}")
            del positions[symbol]
            return
        if price >= tp:
            pnl = (tp - entry) * qty
            balance += pnl
            print(f"[PAPER EXIT][TP] {symbol} exit={tp:.6f} pnl={pnl:.2f} balance={balance:.2f}")
            del positions[symbol]
            return

    if side == "short":
        if price >= sl:
            pnl = (entry - sl) * qty
            balance += pnl
            print(f"[PAPER EXIT][SL] {symbol} exit={sl:.6f} pnl={pnl:.2f} balance={balance:.2f}")
            del positions[symbol]
            return
        if price <= tp:
            pnl = (entry - tp) * qty
            balance += pnl
            print(f"[PAPER EXIT][TP] {symbol} exit={tp:.6f} pnl={pnl:.2f} balance={balance:.2f}")
            del positions[symbol]
            return

def maybe_enter(symbol, closes, highs, lows, price):
    global positions, balance

    if symbol in positions:
        return

    if len(positions) >= max_positions:
        return

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)

    if sma20 is None or sma50 is None:
        return

    recent_high = max(highs[-20:-1])
    recent_low = min(lows[-20:-1])

    # LONG breakout
    if price > sma20 > sma50 and price > recent_high:
        sl = min(lows[-5:]) * 0.995
        tp = price + (price - sl) * 2
        qty = calc_qty(price, sl)
        if qty > 0:
            positions[symbol] = {
                "side": "long",
                "entry": price,
                "qty": qty,
                "sl": sl,
                "tp": tp,
            }
            print(f"[PAPER ENTRY][LONG] {symbol} entry={price:.6f} sl={sl:.6f} tp={tp:.6f} qty={qty:.6f}")
        return

    # SHORT breakdown
    if price < sma20 < sma50 and price < recent_low:
        sl = max(highs[-5:]) * 1.005
        tp = price - (sl - price) * 2
        qty = calc_qty(price, sl)
        if qty > 0:
            positions[symbol] = {
                "side": "short",
                "entry": price,
                "qty": qty,
                "sl": sl,
                "tp": tp,
            }
            print(f"[PAPER ENTRY][SHORT] {symbol} entry={price:.6f} sl={sl:.6f} tp={tp:.6f} qty={qty:.6f}")
        return

while True:
    try:
        print("===================================")
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
                print(f"Failed to fetch {symbol}")
                continue

            closes = [x[4] for x in data]
            highs = [x[2] for x in data]
            lows = [x[3] for x in data]
            price = closes[-1]

            print(f"{symbol} price: {price}")

            check_exit(symbol, price)
            maybe_enter(symbol, closes, highs, lows, price)

        if positions:
            print("Open positions snapshot:")
            for sym, pos in positions.items():
                print(f" - {sym} | {pos['side']} | entry={pos['entry']:.6f} sl={pos['sl']:.6f} tp={pos['tp']:.6f}")
        else:
            print("No open positions")

        print(f"Sleeping {loop_seconds} seconds...")
        time.sleep(loop_seconds)

    except Exception as e:
        print(f"[FATAL ERROR] {e}")
        traceback.print_exc()
        time.sleep(15)
