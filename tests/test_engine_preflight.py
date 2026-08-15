import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from app import engine


class FakeAlpaca:
    def __init__(self, orders=None):
        self.orders=orders or []
        self.submitted=[]

    async def clock(self):
        return {"is_open":True,"next_close":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}
    async def risk_status(self): return {"blocked":False}
    async def positions(self): return []
    async def open_orders(self): return self.orders
    async def account(self): return {"equity":"20000","buying_power":"20000"}
    async def submit_order(self,payload):
        self.submitted.append(payload)
        return {"id":"paper-order","client_order_id":payload["client_order_id"]}


def candidate():
    return {"symbol":"AAAA","setup":"PULLBACK_RECLAIM","entry":10.0,"stop":9.5,
            "target":11.0,"score":90,"intel_score":91,"grade":"A","rvol":3,
            "latest_bar_volume":1000,"avg_daily_volume_20d":1_000_000,
            "data_quality":{"execution_allowed":True,"status":"GOOD"},
            "decision":{"action":"ARM"}}


@pytest.fixture
def configured(monkeypatch):
    engine.COOLDOWNS.clear(); engine.LAST_PREFLIGHT=None
    monkeypatch.setattr(engine,"settings",dataclasses.replace(
        engine.settings,paper=True,enable_orders=True,require_fresh_market_data=True,
        require_liquidity_for_orders=True,max_bar_participation_pct=.05,
        max_daily_participation_pct=.001,max_gross_exposure_pct=.6,
        max_portfolio_heat_pct=.02,buying_power_buffer_pct=.05,
    ))
    monkeypatch.setattr(engine,"_opening_delay_active",lambda:False)
    monkeypatch.setattr(engine,"_entry_window_closed",lambda clock:False)
    monkeypatch.setattr(engine,"position_size",lambda equity,entry,stop:100)
    events=[]
    monkeypatch.setattr(engine,"log_event",lambda *args:events.append(args))
    return events


@pytest.mark.asyncio
async def test_engine_blocks_a_duplicate_working_entry(configured,monkeypatch):
    broker=FakeAlpaca([{"symbol":"AAAA","side":"buy","type":"limit","status":"new",
                       "qty":10,"filled_qty":0,"limit_price":10}])
    monkeypatch.setattr(engine,"alpaca",broker)
    await engine.maybe_place_paper_order(candidate())
    assert broker.submitted == []
    assert "working_entry_order" in engine.LAST_PREFLIGHT["blockers"]


@pytest.mark.asyncio
async def test_engine_submits_only_the_liquidity_approved_quantity(configured,monkeypatch):
    broker=FakeAlpaca()
    monkeypatch.setattr(engine,"alpaca",broker)
    await engine.maybe_place_paper_order(candidate())
    assert broker.submitted[0]["qty"] == "50"
    assert broker.submitted[0]["client_order_id"].startswith("basel-auto-aaaa-pullbackreclaim-")
    assert engine.LAST_PREFLIGHT["allowed"] is True
