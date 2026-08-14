from datetime import datetime, timedelta, timezone

from app.backtest.broker import PendingOrder, SimulatedBroker
from app.backtest.config import ExecutionModel

NOW = datetime(2024, 3, 4, 15, 0, tzinfo=timezone.utc)


def bar(o, h, l, c, v=10_000):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


def broker(**kwargs):
    return SimulatedBroker(20_000.0, ExecutionModel(**kwargs))


def order(limit=10.0, stop=9.8, target=10.4, qty=100):
    return PendingOrder(symbol="AAAA", limit=limit, stop=stop, target=target, qty=qty, placed_at=NOW)


def test_limit_order_fills_when_the_bar_trades_down_to_it():
    b = broker(); b.place(order())
    b.process_bar("AAAA", bar(10.1, 10.2, 9.95, 10.05), NOW, False)
    assert b.positions["AAAA"].entry_price == 10.0


def test_limit_order_does_not_fill_above_the_limit():
    b = broker(); b.place(order())
    b.process_bar("AAAA", bar(10.1, 10.3, 10.05, 10.2), NOW, False)
    assert "AAAA" not in b.positions
    assert b.pending["AAAA"].bars_waited == 1


def test_a_gap_below_the_limit_fills_at_the_better_open():
    b = broker(); b.place(order())
    b.process_bar("AAAA", bar(9.90, 10.0, 9.85, 9.95), NOW, False)
    assert b.positions["AAAA"].entry_price == 9.90


def test_unfilled_orders_expire():
    b = broker(entry_timeout_bars=3); b.place(order())
    for _ in range(3):
        b.process_bar("AAAA", bar(10.5, 10.6, 10.4, 10.5), NOW, False)
    assert "AAAA" not in b.pending
    assert b.cancelled == 1


def test_order_is_rejected_when_cash_is_short():
    b = SimulatedBroker(500.0, ExecutionModel()); b.place(order(qty=100))
    b.process_bar("AAAA", bar(10.0, 10.1, 9.9, 10.0), NOW, False)
    assert b.positions == {} and b.cancelled == 1


def test_target_exit_books_the_limit_price():
    b = broker(); b.place(order())
    b.process_bar("AAAA", bar(10.0, 10.0, 9.9, 10.0), NOW, False)
    trade = b.process_bar("AAAA", bar(10.1, 10.5, 10.05, 10.45), NOW + timedelta(minutes=1), False)
    assert trade.reason == "take_profit" and trade.exit_price == 10.4


def test_stop_exit_pays_slippage():
    b = broker(stop_slippage_bps=10); b.place(order())
    b.process_bar("AAAA", bar(10.0, 10.0, 9.9, 10.0), NOW, False)
    trade = b.process_bar("AAAA", bar(9.95, 9.98, 9.70, 9.75), NOW + timedelta(minutes=1), False)
    assert trade.reason == "stop_loss"
    assert trade.exit_price == 9.8 * (1 - 10/10_000)


def test_a_gap_through_the_stop_fills_at_the_open():
    b = broker(stop_slippage_bps=0); b.place(order())
    b.process_bar("AAAA", bar(10.0, 10.0, 9.9, 10.0), NOW, False)
    trade = b.process_bar("AAAA", bar(9.50, 9.55, 9.40, 9.45), NOW + timedelta(minutes=1), False)
    assert trade.exit_price == 9.50


def test_stop_wins_when_one_bar_spans_both_levels():
    b = broker(same_bar_stop_first=True); b.place(order())
    b.process_bar("AAAA", bar(10.0, 10.0, 9.9, 10.0), NOW, False)
    trade = b.process_bar("AAAA", bar(10.0, 10.5, 9.7, 10.2), NOW + timedelta(minutes=1), False)
    assert trade.reason == "stop_loss"


def test_target_can_win_the_same_bar_when_configured():
    b = broker(same_bar_stop_first=False); b.place(order())
    b.process_bar("AAAA", bar(10.0, 10.0, 9.9, 10.0), NOW, False)
    trade = b.process_bar("AAAA", bar(10.0, 10.5, 9.7, 10.2), NOW + timedelta(minutes=1), False)
    assert trade.reason == "take_profit"


def test_a_bar_never_both_opens_and_closes_a_trade():
    b = broker(); b.place(order())
    # This bar dips to the limit and then collapses far below the stop.
    b.process_bar("AAAA", bar(10.1, 10.2, 9.0, 9.1), NOW, False)
    assert "AAAA" in b.positions and b.trades == []


def test_cash_accounting_round_trips():
    b = broker(); b.place(order(qty=100))
    b.process_bar("AAAA", bar(10.0, 10.1, 9.95, 10.0), NOW, False)
    assert b.cash == 20_000.0 - 1_000.0
    b.close("AAAA", 10.5, NOW, "manual")
    assert b.cash == 20_000.0 + 50.0
    assert b.trades[0].pnl == 50.0


def test_r_multiple_uses_the_real_entry_stop():
    b = broker(); b.place(order(limit=10.0, stop=9.5, qty=10))
    b.process_bar("AAAA", bar(10.0, 10.1, 9.95, 10.0), NOW, False)
    b.close("AAAA", 11.0, NOW, "manual")
    assert b.trades[0].r_multiple == 2.0


def test_true_initial_risk_is_recorded_on_the_position():
    b = broker(); b.place(order(limit=10.0, stop=9.6))
    b.process_bar("AAAA", bar(10.0, 10.1, 9.95, 10.0), NOW, True)
    assert round(b.positions["AAAA"].state.risk_per_share(), 4) == 0.4


def test_live_fallback_risk_is_used_when_not_enabled():
    b = broker(); b.place(order(limit=10.0, stop=9.6))
    b.process_bar("AAAA", bar(10.0, 10.1, 9.95, 10.0), NOW, False)
    assert round(b.positions["AAAA"].state.risk_per_share(), 4) == 0.15
