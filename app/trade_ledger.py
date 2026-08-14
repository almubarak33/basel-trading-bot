from __future__ import annotations
from collections import defaultdict
from datetime import datetime


def _f(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default


def _ts(value: str | None) -> str | None:
    if not value: return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except Exception:
        return value


def build_round_trips(fills: list[dict]) -> list[dict]:
    """Reconstruct long-only round trips from chronological broker fills.

    Basel Trader currently opens long equity positions only. Buys increase the
    weighted-average cost; sells realize P&L. A completed trade is emitted when
    inventory for a symbol returns to flat. Partial exits are accumulated into
    the same round trip rather than counted as separate wins/losses.
    """
    state = defaultdict(lambda: {
        "qty": 0.0, "cost": 0.0, "entry_qty": 0.0, "entry_cost": 0.0,
        "sale_qty": 0.0, "sale_value": 0.0, "realized": 0.0,
        "opened_at": None, "last_sell_at": None,
    })
    closed=[]

    ordered=sorted(fills or [], key=lambda x: x.get("transaction_time") or "")
    for fill in ordered:
        symbol=str(fill.get("symbol") or "").upper()
        side=str(fill.get("side") or "").lower()
        qty=abs(_f(fill.get("qty")))
        price=_f(fill.get("price"))
        if not symbol or qty<=0 or price<=0 or side not in {"buy","sell"}: continue
        s=state[symbol]
        when=_ts(fill.get("transaction_time"))

        if side=="buy":
            if s["qty"] <= 1e-9:
                s.update({"qty":0.0,"cost":0.0,"entry_qty":0.0,"entry_cost":0.0,
                          "sale_qty":0.0,"sale_value":0.0,"realized":0.0,
                          "opened_at":when,"last_sell_at":None})
            s["qty"] += qty
            s["cost"] += qty*price
            s["entry_qty"] += qty
            s["entry_cost"] += qty*price
            continue

        # Ignore sells that cannot be paired with a buy inside the fetched history.
        if s["qty"] <= 1e-9: continue
        sell_qty=min(qty,s["qty"])
        avg_cost=(s["cost"]/s["qty"]) if s["qty"]>0 else 0.0
        basis=sell_qty*avg_cost
        proceeds=sell_qty*price
        s["realized"] += proceeds-basis
        s["sale_qty"] += sell_qty
        s["sale_value"] += proceeds
        s["qty"] -= sell_qty
        s["cost"] -= basis
        s["last_sell_at"] = when

        if s["qty"] <= 1e-8:
            entry=(s["entry_cost"]/s["entry_qty"]) if s["entry_qty"] else 0.0
            exit_price=(s["sale_value"]/s["sale_qty"]) if s["sale_qty"] else 0.0
            pnl=s["realized"]
            invested=s["entry_cost"]
            closed.append({
                "symbol":symbol,
                "qty":round(s["entry_qty"],6),
                "entry":round(entry,4),
                "exit":round(exit_price,4),
                "pnl":round(pnl,2),
                "pnl_pct":round((pnl/invested*100) if invested else 0.0,2),
                "opened_at":s["opened_at"],
                "closed_at":s["last_sell_at"],
                "reason":"broker_fill",
                "source":"alpaca_fill_ledger",
            })
            s.update({"qty":0.0,"cost":0.0,"entry_qty":0.0,"entry_cost":0.0,
                      "sale_qty":0.0,"sale_value":0.0,"realized":0.0,
                      "opened_at":None,"last_sell_at":None})

    closed.sort(key=lambda x:x.get("closed_at") or "", reverse=True)
    return closed
