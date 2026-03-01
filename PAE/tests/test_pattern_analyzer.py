"""Tests for pattern_rules matching logic.

The strategy directory uses a hyphen (propaganda-arbitrage) which is illegal in
Python dotted import paths, so we load the module from its file path via importlib.
"""

import importlib.util
import pathlib
import pytest


def _load_pattern_rules():
    """Load pattern_rules from the hyphenated strategy directory."""
    path = (
        pathlib.Path(__file__).parent.parent
        / "strategies"
        / "propaganda-arbitrage"
        / "pattern_rules.py"
    )
    spec = importlib.util.spec_from_file_location("pattern_rules", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PATTERN_RULES


PATTERN_RULES = _load_pattern_rules()


def matches_rule(rule: dict, text: str) -> bool:
    """Return True if *text* triggers *rule* (keyword hit + no exclusion hit)."""
    text_lower = text.lower()
    keyword_hit = any(kw.lower() in text_lower for kw in rule["keywords"])
    exclude_hit = any(ex.lower() in text_lower for ex in rule.get("exclude", []))
    return keyword_hit and not exclude_hit


class TestPatternRules:
    def test_all_rules_have_required_fields(self):
        required = {"name", "keywords", "signal_type", "confidence", "tickers"}
        for rule in PATTERN_RULES:
            missing = required - rule.keys()
            assert not missing, f"Rule {rule.get('name')!r} missing fields: {missing}"

    def test_confidence_in_range(self):
        for rule in PATTERN_RULES:
            assert 0.0 <= rule["confidence"] <= 1.0, (
                f"Rule {rule['name']!r} has out-of-range confidence: {rule['confidence']}"
            )

    def test_signal_type_valid(self):
        valid = {"bullish", "bearish", "neutral"}
        for rule in PATTERN_RULES:
            assert rule["signal_type"] in valid, (
                f"Rule {rule['name']!r} has invalid signal_type: {rule['signal_type']!r}"
            )

    def test_sanctions_announcement_fires(self):
        rule = next(r for r in PATTERN_RULES if r["name"] == "sanctions_announcement")
        assert matches_rule(rule, "US imposes new sanctions on Russian oil companies")

    def test_sanctions_announcement_excluded_on_relief(self):
        rule = next(r for r in PATTERN_RULES if r["name"] == "sanctions_announcement")
        assert not matches_rule(rule, "Sanctions lifted on Iranian banks after deal")

    def test_tariff_increase_fires(self):
        rule = next(r for r in PATTERN_RULES if r["name"] == "tariff_increase")
        assert matches_rule(rule, "White House announces 25% tariff on Chinese steel")

    def test_defence_spending_fires(self):
        rule = next(r for r in PATTERN_RULES if r["name"] == "defence_spending_increase")
        assert matches_rule(rule, "Congress approves $95B defense spending supplemental")

    def test_no_duplicate_rule_names(self):
        names = [r["name"] for r in PATTERN_RULES]
        assert len(names) == len(set(names)), "Duplicate rule names detected"
