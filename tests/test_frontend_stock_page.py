from pathlib import Path


HTML = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text()


def test_stock_page_offers_every_chart_timeframe():
    for timeframe in ("1Min", "5Min", "15Min", "30Min", "1Hour", "4Hour", "1Day", "1Week", "1Month"):
        assert f"'{timeframe}'" in HTML
    assert "/chart?timeframe=" in HTML


def test_stock_dates_are_explicitly_gregorian():
    assert "ar-SA-u-ca-gregory-nu-latn" in HTML
    assert "Intl.DateTimeFormat('ar-SA'" not in HTML
    assert "toLocaleDateString('ar-SA'" not in HTML


def test_stock_page_loads_heavy_sections_progressively():
    assert "/details`,'details',renderStockDetails" in HTML
    assert "/fundamentals`,'fundamentals',renderStockFundamentals" in HTML
    assert "PAGE==='stockPage'" in HTML
