"""Alpaca rejects a repeated client_order_id, so every submission needs a fresh one."""
import re

import pytest

from app.orders import MAX_CLIENT_ORDER_ID, build_bracket_order, build_client_order_id


# ---- client_order_id ----------------------------------------------------

def test_repeated_orders_for_one_symbol_get_distinct_ids():
    """The regression this fixes: a symbol-only id blocked every later order."""
    ids = {build_client_order_id("AAAA", "intel") for _ in range(200)}
    assert len(ids) == 200


def test_the_id_carries_the_symbol_and_source_for_tracing():
    order_id = build_client_order_id("AAAA", "intel")
    assert order_id.startswith("basel-intel-aaaa-")


def test_manual_and_automated_orders_are_distinguishable():
    assert "-manual-" in build_client_order_id("AAAA", "manual")
    assert "-intel-" in build_client_order_id("AAAA", "intel")


def test_the_id_stays_within_alpacas_limit():
    order_id = build_client_order_id("A" * 40, "intel")
    assert len(order_id) <= MAX_CLIENT_ORDER_ID


@pytest.mark.parametrize("symbol", ["BRK.A", "AA-B", "aa bb", "AA/WS"])
def test_punctuation_in_a_ticker_is_stripped(symbol):
    order_id = build_client_order_id(symbol, "intel")
    assert re.fullmatch(r"[a-z0-9-]+", order_id), order_id


def test_an_unusable_symbol_still_produces_a_valid_id():
    assert build_client_order_id("...", "intel").startswith("basel-intel-sym-")


# ---- bracket payload ----------------------------------------------------

def order(**kwargs):
    base = dict(symbol="aaaa", qty=10, entry=10.005, stop=9.5, target=11.0, source="intel")
    base.update(kwargs)
    return build_bracket_order(**base)


def test_payload_is_a_day_limit_bracket_buy():
    payload = order()
    assert payload["side"] == "buy"
    assert payload["type"] == "limit"
    assert payload["time_in_force"] == "day"
    assert payload["order_class"] == "bracket"


def test_symbol_is_upper_cased_and_quantity_is_a_string():
    payload = order(symbol="aaaa", qty=7)
    assert payload["symbol"] == "AAAA"
    assert payload["qty"] == "7"


def test_prices_are_rounded_to_cents_as_strings():
    payload = order(entry=10.005, stop=9.4949, target=11.019)
    assert payload["limit_price"] == "10.01"
    assert payload["stop_loss"]["stop_price"] == "9.49"
    assert payload["take_profit"]["limit_price"] == "11.02"


def test_both_protective_legs_are_attached():
    payload = order()
    assert payload["take_profit"]["limit_price"] == "11.0"
    assert payload["stop_loss"]["stop_price"] == "9.5"


def test_two_payloads_for_one_symbol_differ_only_by_id():
    first, second = order(), order()
    assert first["client_order_id"] != second["client_order_id"]
    first.pop("client_order_id"); second.pop("client_order_id")
    assert first == second


def test_engine_and_manual_paths_build_the_same_shape():
    from app import engine, main
    assert engine.build_bracket_order is build_bracket_order
    assert main.build_bracket_order is build_bracket_order
