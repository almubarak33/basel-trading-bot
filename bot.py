import os
import json
import math
import time
import traceback
from datetime import datetime, timedelta, timezone

import yaml
import ccxt


STATE_FILE = "state.json"


def utc_now():
    return datetime.now(timezone.utc)


def log(msg: str) -> None:
    print(f"[{utc_now().isoformat()}] {msg}", flush=True)


def load_config() -> dict:
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"positions": {}, "cooldowns": {}, "daily_pnl": {"date": "", "pnl": 0.0}}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_exchange() -> ccxt.binanceusdm:
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    if not api_key or not api_secret:
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET غير موجودة في Variables")

    ex = ccxt.binanceusdm({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    return ex


def ema(values, length):
    if len(values) < length:
        return None
    k = 2 / (length + 1)
    out = values[0]
    for v in values[1:]:
        out = v * k + out * (1 - k)
    return out


def rsi(values, length=14):
    if len(values) < length + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:length]) / length
    avg_loss = sum(losses[:length]) / length
    for i in range(length, len(gains)):
        avg_gain = (avg_gain * (length - 1) + gains[i]) / length
        avg_loss = (avg_loss * (length - 1) + losses[i]) / length
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(ohlcv, length=14):
    if len(ohlcv) < length + 1:
        return None
    trs = []
    for i in range(1, len(ohlcv)):
        high = ohlcv[i][2]
        low = ohlcv[i][3]
        prev_close = ohlcv[i - 1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-length:]) / length


def safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def today_str():
    return utc_now().strftime("%Y-%m-%d")


def reset_daily_pnl_if_needed(state: dict):
    if state["daily_pnl"]["date"] != today_str():
        state["daily_pnl"] = {"date": today_str(), "pnl": 0.0}


def add_daily_pnl(state: dict, pnl: float):
    reset_daily_pnl_if_needed(state)
    state["daily_pnl"]["pnl"] += pnl


def daily_loss_hit(state: dict, cfg: dict) -> bool:
    reset_daily_pnl_if_needed(state)
    return state["daily_pnl"]["pnl"] <= -abs(float(cfg["daily_loss_limit_usd"]))


def load_markets_and_candidates(ex, cfg):
    markets = ex.load_markets()
    tickers = ex.fetch_tickers()

    candidates = []
    for symbol, market in markets.items():
        if not market.get("active", True):
            continue
        if not market.get("contract", False):
            continue
        if market.get("linear") is not True:
            continue
        if market.get("quote") != "USDT":
            continue
        if market.get("expiry") is not None:
            continue
        if symbol in cfg["filters"].get("exclude_symbols", []):
            continue

        t = tickers.get(symbol)
        if not t:
            continue

        last = safe_float(t.get("last"))
        quote_volume = safe_float(t.get("quoteVolume"))
        if last <= 0:
            continue
        if last < float(cfg["filters"]["min_price"]) or last > float(cfg["filters"]["max_price"]):
            continue
        if quote_volume < float(cfg["min_quote_volume_usd"]):
            continue

        candidates.append((symbol, quote_volume))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in candidates[: int(cfg["scan_top_n"])]]


def fetch_ohlcv_safe(ex, symbol, timeframe, limit, retries=3):
    for i in range(retries):
        try:
            return ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            log(f"[ERROR] fetch_ohlcv {symbol} try={i+1}: {e}")
            time.sleep(1.5)
    return None


def get_signal(ohlcv, cfg):
    closes = [c[4] for c in ohlcv]
    highs = [c[2] for c in ohlcv]
    lows = [c[3] for c in ohlcv]
    price = closes[-1]

    s = cfg["strategy"]
    ema_fast = ema(closes, int(s["ema_fast"]))
    ema_slow = ema(closes, int(s["ema_slow"]))
    ema_trend = ema(closes, int(s["ema_trend"]))
    r = rsi(closes, int(s["rsi_length"]))
    a = atr(ohlcv, int(s["atr_length"]))

    if None in (ema_fast, ema_slow, ema_trend, r, a):
        return None

    recent_high = max(highs[-20:-1])
    recent_low = min(lows[-20:-1])

    # Long
    if price > ema_trend and ema_fast > ema_slow and 52 <= r <= 68 and price > recent_high:
        sl = price - a * float(s["atr_sl_mult"])
        tp = price + (price - sl) * float(s["rr"])
        return {"side": "buy", "entry": price, "sl": sl, "tp": tp}

    # Short
    if price < ema_trend and ema_fast < ema_slow and 32 <= r <= 48 and price < recent_low:
        sl = price + a * float(s["atr_sl_mult"])
        tp = price - (sl - price) * float(s["rr"])
        return {"side": "sell", "entry": price, "sl": sl, "tp": tp}

    return None


def amount_for_risk(symbol, entry, sl, risk_usd):
    dist = abs(entry - sl)
    if dist <= 0:
        return 0.0
    qty = risk_usd / dist
    return qty


def normalize_amount(ex, symbol, amount):
    try:
        amt = ex.amount_to_precision(symbol, amount)
        return float(amt)
    except Exception:
        return float(amount)


def normalize_price(ex, symbol, price):
    try:
        px = ex.price_to_precision(symbol, price)
        return float(px)
    except Exception:
        return float(price)


def set_symbol_risk_params(ex, symbol, cfg):
    lev = int(cfg["leverage"])
    margin_mode = cfg["margin_mode"]
    try:
        ex.set_margin_mode(margin_mode, symbol)
    except Exception as e:
        log(f"[WARN] set_margin_mode {symbol}: {e}")
    try:
        ex.set_leverage(lev, symbol)
    except Exception as e:
        log(f"[WARN] set_leverage {symbol}: {e}")


def place_entry(ex, symbol, signal, qty):
    side = signal["side"]
    order = ex.create_order(symbol, "market", side, qty, None, {})
    return order


def place_protection_orders(ex, symbol, signal, qty):
    side = signal["side"]
    opposite = "sell" if side == "buy" else "buy"
    sl = signal["sl"]
    tp = signal["tp"]

    sl = normalize_price(ex, symbol, sl)
    tp = normalize_price(ex, symbol, tp)

    # وقف خسارة
    sl_order = ex.create_order(
        symbol,
        "STOP_MARKET",
        opposite,
        qty,
        None,
        {
            "stopPrice": sl,
            "reduceOnly": True,
            "workingType": "MARK_PRICE",
        },
    )

    # هدف
    tp_order = ex.create_order(
        symbol,
        "TAKE_PROFIT_MARKET",
        opposite,
        qty,
        None,
        {
            "stopPrice": tp,
            "reduceOnly": True,
            "workingType": "MARK_PRICE",
        },
    )
    return sl_order, tp_order


def fetch_open_positions(ex):
    out = {}
    try:
        positions = ex.fetch_positions()
    except Exception as e:
        log(f"[WARN] fetch_positions: {e}")
        return out

    for p in positions:
        contracts = safe_float(p.get("contracts"))
        if contracts <= 0:
            continue
        symbol = p.get("symbol")
        side = p.get("side")
        entry = safe_float(p.get("entryPrice"))
        unrealized = safe_float(p.get("unrealizedPnl"))
        out[symbol] = {
            "side": side,
            "contracts": contracts,
            "entry": entry,
            "unrealized": unrealized,
        }
    return out


def close_position_market(ex, symbol, side, qty):
    opposite = "sell" if side == "buy" else "buy"
    return ex.create_order(symbol, "market", opposite, qty, None, {"reduceOnly": True})


def cancel_symbol_orders(ex, symbol):
    try:
        ex.cancel_all_orders(symbol)
    except Exception as e:
        log(f"[WARN] cancel_all_orders {symbol}: {e}")


def main():
    cfg = load_config()
    state = load_state()
    reset_daily_pnl_if_needed(state)
    ex = get_exchange()

    log("=== LIVE BOT STARTED ===")
    log("تنبيه: هذا بوت تداول حقيقي. استخدم مفاتيح API بدون سحب وبمبلغ صغير.")

    while True:
        try:
            cfg = load_config()
            reset_daily_pnl_if_needed(state)

            if bool(cfg.get("emergency_close_all", False)):
                log("[EMERGENCY] إغلاق كل المراكز وإلغاء الأوامر")
                open_pos = fetch_open_positions(ex)
                for sym, p in open_pos.items():
                    cancel_symbol_orders(ex, sym)
                    side = "buy" if p["side"] == "long" else "sell"
                    close_position_market(ex, sym, side, p["contracts"])
                state["positions"] = {}
                save_state(state)
                time.sleep(int(cfg["loop_seconds"]))
                continue

            if not bool(cfg.get("enabled", True)):
                log("[PAUSED] enabled=false → لا توجد صفقات جديدة")
                time.sleep(int(cfg["loop_seconds"]))
                continue

            if daily_loss_hit(state, cfg):
                log("[DAILY STOP] تم الوصول لحد الخسارة اليومية، لا توجد صفقات جديدة")
                time.sleep(int(cfg["loop_seconds"]))
                continue

            log("Scanning market...")

            candidates = load_markets_and_candidates(ex, cfg)
            open_pos = fetch_open_positions(ex)

            # تنظيف الحالة للمراكز المغلقة
            active_symbols = set(open_pos.keys())
            for sym in list(state["positions"].keys()):
                if sym not in active_symbols:
                    state["positions"].pop(sym, None)

            # تحديث اللوق للمراكز
            if open_pos:
                for sym, p in open_pos.items():
                    log(f"[OPEN] {sym} side={p['side']} qty={p['contracts']} entry={p['entry']} upnl={p['unrealized']}")
            else:
                log("No open positions")

            if len(open_pos) >= int(cfg["max_positions"]):
                log("Max positions reached")
                save_state(state)
                time.sleep(int(cfg["loop_seconds"]))
                continue

            for symbol in candidates:
                if len(open_pos) >= int(cfg["max_positions"]):
                    break

                if symbol in open_pos:
                    continue

                cooldowns = state.get("cooldowns", {})
                cd_until = cooldowns.get(symbol)
                if cd_until:
                    try:
                        if utc_now() < datetime.fromisoformat(cd_until):
                            continue
                    except Exception:
                        pass

                ohlcv = fetch_ohlcv_safe(ex, symbol, cfg["timeframe"], int(cfg["ohlcv_limit"]))
                if not ohlcv:
                    continue

                signal = get_signal(ohlcv, cfg)
                if not signal:
                    continue

                set_symbol_risk_params(ex, symbol, cfg)

                qty = amount_for_risk(
                    symbol=symbol,
                    entry=signal["entry"],
                    sl=signal["sl"],
                    risk_usd=float(cfg["risk_per_trade_usd"]),
                )
                qty = normalize_amount(ex, symbol, qty)

                if qty <= 0:
                    log(f"[SKIP] qty<=0 {symbol}")
                    continue

                log(
                    f"[ENTRY SIGNAL] {symbol} side={signal['side']} "
                    f"entry={signal['entry']:.6f} sl={signal['sl']:.6f} tp={signal['tp']:.6f} qty={qty}"
                )

                entry_order = place_entry(ex, symbol, signal, qty)
                time.sleep(1.5)
                sl_order, tp_order = place_protection_orders(ex, symbol, signal, qty)

                state["positions"][symbol] = {
                    "side": signal["side"],
                    "qty": qty,
                    "entry_order_id": entry_order.get("id"),
                    "sl_order_id": sl_order.get("id"),
                    "tp_order_id": tp_order.get("id"),
                    "opened_at": utc_now().isoformat(),
                }

                state["cooldowns"][symbol] = (utc_now() + timedelta(minutes=int(cfg["cooldown_minutes"]))).isoformat()
                save_state(state)

                log(f"[LIVE ENTRY] {symbol} side={signal['side']} qty={qty}")
                open_pos = fetch_open_positions(ex)

            save_state(state)
            log(f"Sleeping {cfg['loop_seconds']} seconds...")
            time.sleep(int(cfg["loop_seconds"]))

        except Exception as e:
            log(f"[FATAL] {e}")
            traceback.print_exc()
            time.sleep(10)


if __name__ == "__main__":
    main()
