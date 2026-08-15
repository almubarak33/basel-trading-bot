import re

import pytest

from app.intelligence import enrich_candidate, market_brief
from app.messages import DEFAULT_LANGUAGE, LANGUAGES, MESSAGES, MessageList, render
from app.strategy import build_candidate

PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Codes whose English and Arabic are legitimately identical because the string
# carries no translatable words — only ticker symbols and placeholders.
IDENTICAL_BY_DESIGN = {"regime_label"}


@pytest.mark.parametrize("code", sorted(MESSAGES))
def test_every_message_covers_every_language(code):
    for lang in LANGUAGES:
        assert MESSAGES[code].get(lang), f"{code} is missing a {lang} translation"


@pytest.mark.parametrize("code", sorted(MESSAGES))
def test_placeholders_match_across_languages(code):
    """A translation that drops {value} would silently swallow the number."""
    expected = PLACEHOLDER.findall(MESSAGES[code][DEFAULT_LANGUAGE])
    for lang in LANGUAGES:
        assert PLACEHOLDER.findall(MESSAGES[code][lang]) == expected, \
            f"{code} placeholders differ in {lang}"


@pytest.mark.parametrize("code", sorted(MESSAGES))
def test_arabic_is_actually_translated(code):
    """Catches English text pasted into the Arabic slot."""
    if code in IDENTICAL_BY_DESIGN:
        return
    english, arabic = MESSAGES[code]["en"], MESSAGES[code]["ar"]
    if not re.search(r"[A-Za-z]", english):
        return
    assert arabic != english, f"{code} was never translated"


def test_render_substitutes_parameters():
    assert render("rvol", {"value": "3.20x"}, "en") == "RVOL 3.20x"
    assert "3.20x" in render("rvol", {"value": "3.20x"}, "ar")


def test_units_travel_with_the_value_not_the_template():
    """A unit left in the template detaches from its number under Arabic bidi."""
    for code in ("rvol", "spread", "vwap_extension", "strong_rvol", "healthy_rvol", "chip_risk"):
        for lang in LANGUAGES:
            template = MESSAGES[code][lang]
            assert "{value}%" not in template and "{value}x" not in template, \
                f"{code} ({lang}) keeps its unit outside the placeholder"


def test_render_falls_back_to_english_for_an_unknown_language():
    assert render("tight_spread", lang="fr") == MESSAGES["tight_spread"]["en"]


def test_render_returns_the_code_when_it_is_unknown():
    assert render("no_such_code") == "no_such_code"


def test_message_list_keeps_codes_and_text_in_step():
    bag = MessageList()
    bag.add("pullback_detected")
    bag.add("rvol", value="4.00x")
    assert bag.codes == [{"code": "pullback_detected"}, {"code": "rvol", "params": {"value": "4.00x"}}]
    assert bag.texts("en") == ["Controlled pullback detected", "RVOL 4.00x"]
    assert bag.texts("ar")[1].endswith("4.00x")


def test_empty_message_list_is_falsy():
    assert not MessageList()


# ---- every code the engine can emit must exist in the catalog ----------

def candidate_row(**kwargs):
    bars = [{"o": 10, "h": 10.1, "l": 9.9, "c": 10, "v": 1000} for _ in range(40)]
    defaults = dict(symbol="AAAA", change_pct=8.0, volume_rank=3,
                    snapshot={"latestTrade": {"p": 10.0}, "latestQuote": {"bp": 9.99, "ap": 10.01}},
                    bars=bars, avg_daily_volume=100_000, session_fraction=0.5)
    defaults.update(kwargs)
    return build_candidate(**defaults)


def test_strategy_emits_only_known_codes():
    for candidate in (candidate_row(), candidate_row(change_pct=0.0), candidate_row(bars=[])):
        for item in candidate.reason_codes + candidate.reject_codes:
            assert item["code"] in MESSAGES, f"unknown code {item['code']}"


def test_strategy_text_matches_its_codes():
    candidate = candidate_row()
    assert candidate.reject_reasons == [render(c["code"], c.get("params")) for c in candidate.reject_codes]
    assert candidate.reasons == [render(c["code"], c.get("params")) for c in candidate.reason_codes]


def test_intelligence_emits_only_known_codes():
    from dataclasses import asdict
    for row in (asdict(candidate_row()), asdict(candidate_row(change_pct=30.0))):
        enriched = enrich_candidate(row)
        for item in enriched["bull_codes"] + enriched["bear_codes"]:
            assert item["code"] in MESSAGES
        assert enriched["decision"]["thesis_code"] in MESSAGES
        assert enriched["catalyst"]["note_code"] in MESSAGES
        assert enriched["insider"]["note_code"] in MESSAGES


@pytest.mark.parametrize("healthy,expected", [(2, "brief_risk_on"), (1, "brief_mixed"), (0, "brief_risk_off")])
def test_market_brief_emits_a_known_code(healthy, expected):
    brief = market_brief({"market_regime": {"healthy_indexes": healthy}})
    assert brief["text_code"] == expected
    assert brief["text"] == render(expected)


def test_conservative_scanner_blocks_a_risk_off_candidate(monkeypatch):
    import dataclasses
    from app import scanner
    from app.scanner import assemble_candidates
    eligible = dataclasses.replace(candidate_row(), eligible=True, reject_reasons=[], reject_codes=[])
    monkeypatch.setattr(scanner, "settings", dataclasses.replace(scanner.settings, trading_profile="CONSERVATIVE"))
    monkeypatch.setattr(scanner, "build_candidate", lambda *args, **kwargs: eligible)
    rows = assemble_candidates(["AAAA"], {"AAAA": 8.0}, {"AAAA": 1}, {}, {}, {},
                               {"longs_allowed": False}, 0.5)
    assert rows[0]["eligible"] is False
    assert {item["code"] for item in rows[0]["reject_codes"]} == {"regime_block"}
    assert "regime_block" in MESSAGES


def test_aggressive_scanner_keeps_a_risk_off_candidate_visible(monkeypatch):
    import dataclasses
    from app import scanner
    from app.scanner import assemble_candidates
    eligible = dataclasses.replace(candidate_row(), eligible=True, reject_reasons=[], reject_codes=[])
    monkeypatch.setattr(scanner, "settings", dataclasses.replace(scanner.settings, trading_profile="AGGRESSIVE"))
    monkeypatch.setattr(scanner, "build_candidate", lambda *args, **kwargs: eligible)
    rows = assemble_candidates(["AAAA"], {"AAAA": 8.0}, {"AAAA": 1}, {}, {}, {},
                               {"longs_allowed": False,
                                "details": {"SPY": {"price": 500, "healthy": False},
                                            "QQQ": {"price": 450, "healthy": False}}}, 0.5)
    assert rows[0]["eligible"] is True
    assert rows[0]["market_regime_caution"] is True
