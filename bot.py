import time
import yaml
import ccxt

print("=== BOT STARTED ===")

# تحميل الإعدادات
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

loop_seconds = config.get("loop_seconds", 60)
symbols_config = config.get("symbols", [])
balance = float(config.get("starting_balance_usd", 10000))
risk_per_trade = float(config.get("risk_per_trade", 0.01))

exchange = ccxt.binanceusdm({
    "enableRateLimit": True
})

positions = {}

def fetch_data(symbol, timeframe, limit):
    try:
        return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as e:
        print(f"[ERROR] {symbol}: {e}")
        return None

def sma(data, length):
    return sum(data[-length:]) / length

while True:
    print("\n============================")
    print(f"Balance: {balance:.2f}")
    print("============================")

    for s in symbols_config:
        symbol = s["symbol"]
        timeframe = s["timeframe"]
        limit = s["limit"]

        print(f"\nChecking {symbol}")

        data = fetch_data(symbol, timeframe, limit)
        if not data:
            continue

        closes = [c[4] for c in data]
        price = closes[-1]

        sma20 = sma(closes, 20)

        print(f"{symbol} price: {price}")
        print(f"SMA20: {sma20}")

        # ===== دخول صفقة =====
        if symbol not in positions:

            # LONG
            if price > sma20:
                entry = price
                sl = price * 0.99
                tp = price * 1.02

                risk_amount = balance * risk_per_trade
                qty = risk_amount / (entry - sl)

                positions[symbol] = {
                    "side": "long",
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "qty": qty
                }

                print(f"[ENTRY LONG] {symbol}")
                print(f"Entry: {entry} | SL: {sl} | TP: {tp} | QTY: {qty}")

            # SHORT
            elif price < sma20:
                entry = price
                sl = price * 1.01
                tp = price * 0.98

                risk_amount = balance * risk_per_trade
                qty = risk_amount / (sl - entry)

                positions[symbol] = {
                    "side": "short",
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "qty": qty
                }

                print(f"[ENTRY SHORT] {symbol}")
                print(f"Entry: {entry} | SL: {sl} | TP: {tp} | QTY: {qty}")

        # ===== إدارة الصفقة =====
        else:
            pos = positions[symbol]
            side = pos["side"]
            entry = pos["entry"]
            sl = pos["sl"]
            tp = pos["tp"]
            qty = pos["qty"]

            # LONG
            if side == "long":
                if price <= sl:
                    pnl = (sl - entry) * qty
                    balance += pnl
                    print(f"[STOP LOSS] {symbol} | PnL: {pnl}")
                    del positions[symbol]

                elif price >= tp:
                    pnl = (tp - entry) * qty
                    balance += pnl
                    print(f"[TAKE PROFIT] {symbol} | PnL: {pnl}")
                    del positions[symbol]

            # SHORT
            elif side == "short":
                if price >= sl:
                    pnl = (entry - sl) * qty
                    balance += pnl
                    print(f"[STOP LOSS] {symbol} | PnL: {pnl}")
                    del positions[symbol]

                elif price <= tp:
                    pnl = (entry - tp) * qty
                    balance += pnl
                    print(f"[TAKE PROFIT] {symbol} | PnL: {pnl}")
                    del positions[symbol]

    if positions:
        print("\nOpen Positions:")
        for sym, p in positions.items():
            print(f"{sym} | {p['side']} | entry={p['entry']}")
    else:
        print("\nNo open positions")

    print("\nSleeping...\n")
    time.sleep(loop_seconds)
