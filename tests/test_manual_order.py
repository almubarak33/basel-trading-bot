"""Manual Paper orders use the same uncapped Runner payload as automation."""
import dataclasses

import pytest

from app import main


class FakeAlpaca:
    def __init__(self):
        self.submitted = None

    def configured(self):
        return True

    async def risk_status(self):
        return {"blocked": False}

    async def account(self):
        return {"equity": "20000"}

    async def positions(self):
        return []

    async def submit_order(self, payload):
        self.submitted = payload
        return {"id": "paper-order"}


@pytest.mark.asyncio
async def test_manual_order_does_not_sell_at_the_2r_reference(monkeypatch):
    broker = FakeAlpaca()
    monkeypatch.setattr(main, "alpaca", broker)
    monkeypatch.setattr(main, "settings", dataclasses.replace(
        main.settings, paper=True, enable_orders=True, max_open_positions=4,
    ))
    monkeypatch.setattr(main, "KILL_SWITCH", False)
    monkeypatch.setattr(main, "position_size", lambda equity, entry, stop: 10)
    monkeypatch.setattr(main, "log_event", lambda *args, **kwargs: None)

    response = await main.paper_order(main.OrderRequest(
        symbol="AAAA", entry=40.0, stop=39.5, target=41.0,
    ))

    assert broker.submitted["order_class"] == "oto"
    assert broker.submitted["stop_loss"]["stop_price"] == "39.5"
    assert "take_profit" not in broker.submitted
    assert response["target_reference"] == 41.0
    assert response["runner_mode"] is True
