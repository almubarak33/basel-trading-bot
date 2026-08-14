from datetime import datetime, timezone

from app.catalyst import analyze_catalyst

NOW = datetime(2026, 8, 14, 17, 0, tzinfo=timezone.utc)


def article(headline, created_at="2026-08-14T16:45:00Z", symbols=None):
    return {"id": 1, "headline": headline, "summary": "", "created_at": created_at,
            "symbols": symbols or ["TEST"], "source": "example"}


def test_recent_contract_is_strong_positive_catalyst():
    result = analyze_catalyst([article("TEST wins major contract award")], NOW)
    assert result["direction"] == "POSITIVE"
    assert result["category"] == "contract"
    assert result["status"] == "STRONG"
    assert result["execution_gate"] is False


def test_recent_offering_is_negative_catalyst():
    result = analyze_catalyst([article("TEST announces registered direct offering")], NOW)
    assert result["direction"] == "NEGATIVE"
    assert result["category"] == "dilution"
    assert result["score"] >= 85


def test_ambiguous_news_stays_neutral():
    result = analyze_catalyst([article("TEST to participate in investor conference")], NOW)
    assert result["direction"] == "NEUTRAL"
    assert result["score"] == 30


def test_no_news_is_not_fabricated():
    result = analyze_catalyst([], NOW)
    assert result["status"] == "NONE"
    assert result["headline"] is None
