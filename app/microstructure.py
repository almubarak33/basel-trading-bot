from __future__ import annotations


def _f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def analyze_microstructure(quote: dict | None, trade: dict | None, price: float = 0.0) -> dict:
    """Score immediate quote quality without making an entry decision.

    This layer is intentionally diagnostic-only for now. Latest quotes expose
    best bid/ask and displayed sizes; latest trade supplies the most recent
    execution. Those are useful for timing and liquidity, but a single snapshot
    is not enough to prove order-flow direction, so the output must not be
    treated as a buy/sell signal by itself.
    """
    q = quote or {}
    t = trade or {}
    bid = _f(q.get("bp"))
    ask = _f(q.get("ap"))
    bid_size = _f(q.get("bs"))
    ask_size = _f(q.get("as"))
    last = _f(t.get("p"), price)

    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 and ask >= bid else None
    displayed = bid_size + ask_size
    imbalance = ((bid_size - ask_size) / displayed) if displayed > 0 else 0.0

    # Where the last execution sits inside the NBBO. Positive = nearer ask,
    # negative = nearer bid. This is a weak instantaneous clue, not true signed
    # order flow, because one latest trade does not describe a sequence.
    trade_location = 0.0
    if mid > 0 and ask > bid:
        trade_location = max(-1.0, min(1.0, (last - mid) / ((ask - bid) / 2)))

    quality = 50.0
    if spread_pct is not None:
        if spread_pct <= 0.15: quality += 25
        elif spread_pct <= 0.30: quality += 15
        elif spread_pct <= 0.45: quality += 5
        else: quality -= 25
    if displayed >= 2000: quality += 10
    elif displayed < 200: quality -= 10
    if imbalance >= 0.25: quality += 8
    elif imbalance <= -0.25: quality -= 8
    if trade_location >= 0.5: quality += 7
    elif trade_location <= -0.5: quality -= 7
    quality = round(max(0.0, min(100.0, quality)), 1)

    if quality >= 75:
        state = "SUPPORTIVE"
    elif quality >= 50:
        state = "NEUTRAL"
    else:
        state = "FRAGILE"

    return {
        "state": state,
        "quality_score": quality,
        "bid": round(bid, 4) if bid else None,
        "ask": round(ask, 4) if ask else None,
        "last": round(last, 4) if last else None,
        "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
        "bid_size": int(bid_size) if bid_size else 0,
        "ask_size": int(ask_size) if ask_size else 0,
        "displayed_imbalance": round(imbalance, 3),
        "trade_location": round(trade_location, 3),
        "execution_gate": False,
        "note": "Diagnostic only: latest quote/trade snapshot, not a standalone order-flow signal.",
    }
