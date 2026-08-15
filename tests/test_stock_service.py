import pytest

from app import stock_service


class FakeAlpaca:
    def __init__(self):
        self.calls = []

    def configured(self): return True

    async def snapshots(self, symbols):
        self.calls.append(("snapshots", tuple(symbols)))
        return {"snapshots": {"FAST": {
            "latestTrade": {"p": 10.5}, "latestQuote": {"bp": 10.49, "ap": 10.51},
            "dailyBar": {"o": 10, "h": 10.7, "l": 9.9, "c": 10.5, "v": 100_000},
            "prevDailyBar": {"c": 10},
        }}}

    async def intraday_bars(self, symbols, minutes=300):
        self.calls.append(("intraday", minutes))
        return {"FAST": [{"t": f"2026-08-14T14:{minute:02d}:00Z", "o": 10,
                          "h": 10.6, "l": 9.9, "c": 10.5, "v": 10_000}
                         for minute in range(40)]}

    async def daily_bars(self, symbols, days=25):
        self.calls.append(("daily", days))
        return {"FAST": [{"t": f"2026-07-{day:02d}T20:00:00Z", "o": 10,
                          "h": 11, "l": 9, "c": 10, "v": 100_000}
                         for day in range(1, 21)]}

    async def market_regime(self): return {"longs_allowed": True, "details": {}}
    async def asset(self, symbol): return {"symbol": symbol, "name": "Fast Corp", "tradable": True}
    async def position(self, symbol): raise RuntimeError("no position")


@pytest.mark.asyncio
async def test_core_loads_one_symbol_directly_and_coalesces_repeats(monkeypatch):
    fake = FakeAlpaca()
    monkeypatch.setattr(stock_service, "alpaca", fake)
    monkeypatch.setattr(stock_service, "analyze_microstructure", lambda *args: {})
    monkeypatch.setattr(stock_service, "assemble_candidates", lambda *args: [{
        "symbol": "FAST", "price": 10.5, "change_pct": 5, "entry": 10.5,
        "stop": 10, "target": 11.5, "score": 80,
    }])
    monkeypatch.setattr(stock_service, "enrich_candidate", lambda row: row)
    stock_service._CACHE.clear()

    first = await stock_service.stock_core("FAST")
    second = await stock_service.stock_core("FAST")

    assert first["symbol"] == second["symbol"] == "FAST"
    assert fake.calls.count(("snapshots", ("FAST",))) == 1
    assert ("intraday", 5 * 24 * 60) in fake.calls
    assert first["asset"]["name"] == "Fast Corp"


@pytest.mark.asyncio
async def test_unsupported_chart_interval_is_rejected_before_network(monkeypatch):
    stock_service._CACHE.clear()
    with pytest.raises(ValueError, match="unsupported_timeframe"):
        await stock_service.stock_chart("FAST", "2Hour")
