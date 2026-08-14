from __future__ import annotations
from datetime import datetime, timezone

POSITIVE_CATEGORIES = {
    "earnings": ("earnings", "revenue", "eps", "guidance", "raises outlook", "beats estimates", "record revenue"),
    "contract": ("contract", "award", "selected by", "purchase order", "partnership", "strategic agreement"),
    "regulatory": ("fda", "approval", "approved", "clearance", "clinical trial", "phase 2", "phase 3"),
    "m&a": ("acquire", "acquisition", "merger", "buyout", "takeover"),
    "analyst": ("upgrade", "price target raised", "initiated with buy", "outperform"),
}
NEGATIVE_CATEGORIES = {
    "dilution": ("offering", "public offering", "registered direct", "atm offering", "warrant", "dilution"),
    "regulatory_risk": ("investigation", "sec probe", "subpoena", "warning letter", "lawsuit"),
    "analyst_negative": ("downgrade", "price target cut", "underperform", "sell rating"),
    "earnings_negative": ("misses estimates", "cuts guidance", "lowers outlook", "revenue miss"),
}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def analyze_catalyst(articles: list[dict] | None, now: datetime | None = None) -> dict:
    """Summarize recent company news without letting headlines trade by themselves.

    This is intentionally explainable and diagnostic-only. It scores recency and
    explicit event phrases, not generic NLP optimism. Unknown/ambiguous headlines
    stay neutral instead of being forced into bullish or bearish labels.
    """
    now = now or datetime.now(timezone.utc)
    rows = articles or []
    if not rows:
        return {
            "status": "NONE", "score": 0, "direction": "NEUTRAL", "category": None,
            "headline": None, "age_minutes": None, "source": None, "execution_gate": False,
            "note": "No recent verified Alpaca news attached to this symbol.",
        }

    ranked = []
    for article in rows:
        headline = str(article.get("headline") or "").strip()
        summary = str(article.get("summary") or "").strip()
        text = f"{headline} {summary}".lower()
        created = _parse_time(article.get("created_at") or article.get("updated_at"))
        age = max(0.0, (now - created).total_seconds()/60) if created else 99999.0

        direction = "NEUTRAL"; category = None; event_weight = 0
        for name, phrases in NEGATIVE_CATEGORIES.items():
            if any(p in text for p in phrases):
                direction = "NEGATIVE"; category = name; event_weight = 70; break
        if direction == "NEUTRAL":
            for name, phrases in POSITIVE_CATEGORIES.items():
                if any(p in text for p in phrases):
                    direction = "POSITIVE"; category = name; event_weight = 65; break

        if age <= 30: recency = 30
        elif age <= 120: recency = 22
        elif age <= 360: recency = 14
        elif age <= 1440: recency = 7
        else: recency = 0
        score = min(100, event_weight + recency)
        ranked.append((score, -age, article, direction, category, age))

    ranked.sort(reverse=True, key=lambda x: (x[0], x[1]))
    score, _, best, direction, category, age = ranked[0]
    status = "STRONG" if score >= 85 else ("MODERATE" if score >= 65 else "WEAK")
    return {
        "status": status,
        "score": int(score),
        "direction": direction,
        "category": category,
        "headline": best.get("headline"),
        "age_minutes": round(age, 1) if age < 99999 else None,
        "source": best.get("source"),
        "url": best.get("url"),
        "article_id": best.get("id"),
        "article_count": len(rows),
        "execution_gate": False,
        "note": "Diagnostic only until catalyst contribution is validated out-of-sample.",
    }
