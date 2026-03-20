import time
import yaml
import ccxt

print("=== FILE LOADED ===")

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

mode = config.get("mode", "paper")
loop_seconds = config.get("loop_seconds", 60)
symbols_config = config.get("symbols", [])
starting_balance = float(config.get("starting_balance_usd", 10000))
risk_per_trade = float(config.get("risk_per_trade", 0.01))

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
        print(f"[ERROR] {symbol}: {e}")
        return None

while True:
    print("\n===================================")
    print("Bot running... checking market")
    print(f"Balance: {balance:.2f}")
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

        closes = [c[4] for c in data]
        price = closes[-1]

        print(f"{symbol} price: {price}")

        # إذا لا توجد صفقة مفتوحة على هذا الرمز، افتح صفقة تجريبية مباشرة
        if symbol not in positions:
            entry = price
            sl = price * 0.995
            tp = price * 1.01

            risk_amount = balance * risk_per_trade
            stop_distance = entry - sl

            if stop_distance <= 0:
                print(f"[SKIP] Invalid stop distance for {symbol}")
                continue

            qty = risk_amount / stop_distance

            positions[symbol] = {
                "side": "long",
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "qty": qty
            }

            print(f"[FORCE ENTRY] {symbol}")
            print(f"Entry: {entry} | SL: {sl} | TP: {tp} | QTY: {qty}")

        # إدارة الصفقة المفتوحة
        else:
            pos = positions[symbol]
            side = pos["side"]
            entry = pos["entry"]
            sl = pos["sl"]
            tp = pos["tp"]
            qty = pos["qty"]

            if side == "long":
                if price <= sl:
                    pnl = (sl - entry) * qty
                    balance += pnl
                    print(f"[STOP LOSS] {symbol} | Exit: {sl} | PnL: {pnl:.2f} | Balance: {balance:.2f}")
                    del positions[symbol]

                elif price >= tp:
                    pnl = (tp - entry) * qty
                    balance += pnl
                    print(f"[TAKE PROFIT] {symbol} | Exit: {tp} | PnL: {pnl:.2f} | Balance: {balance:.2f}")
                    del positions[symbol]

    if positions:
        print("\nOpen Positions:")
        for sym, p in positions.items():
            print(
                f"{sym} | {p['side']} | "
                f"entry={p['entry']:.6f} | sl={p['sl']:.6f} | tp={p['tp']:.6f} | qty={p['qty']:.6f}"
            )
    else:
        print("\nNo open positions")

    print(f"\nSleeping {loop_seconds} seconds...\n")
    time.sleep(loop_seconds)
