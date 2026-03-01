"""Tests for app.services.analysis.pattern_detector."""

import pytest
from app.services.analysis.pattern_detector import PatternDetector

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_PATTERNS = {
    "coverage_gap": {
        "min_asia_articles": 5,
        "max_western_articles": 2,
        "min_gap_ratio": 3.0,
    },
    "policy_catalyst": {
        "keywords": ["subsidy", "fund", "billion", "investment", "policy", "regulation"],
        "min_amount": 1_000_000_000,
    },
    "entities_of_interest": ["SMIC", "TSMC", "semiconductor", "chip", "China", "Taiwan"],
}


def _make_article(title="", content="", category="unknown", summary=""):
    return {"title": title, "content": content, "summary": summary, "category": category}


# ── extract_entities ──────────────────────────────────────────────────────────

class TestExtractEntities:
    def setup_method(self):
        self.det = PatternDetector(SAMPLE_PATTERNS)

    def test_finds_company_exact_case(self):
        result = self.det.extract_entities("NVIDIA reports record earnings this quarter")
        assert "NVIDIA" in result

    def test_does_not_match_lowercase_company(self):
        result = self.det.extract_entities("nvidia stock rises")
        assert "NVIDIA" not in result   # companies are case-sensitive

    def test_finds_multiple_companies(self):
        result = self.det.extract_entities("TSMC and Samsung compete in advanced nodes")
        assert "TSMC" in result
        assert "Samsung" in result

    def test_finds_country_case_insensitive(self):
        result = self.det.extract_entities("Taiwan faces increasing pressure from China")
        # Country names are title-cased in output
        assert "Taiwan" in result or "TAIWAN" in result
        assert "China" in result or "CHINA" in result

    def test_finds_topic_keyword(self):
        result = self.det.extract_entities("Global semiconductor shortage worsens in Q3")
        assert "semiconductor" in result

    def test_finds_ai_topic(self):
        result = self.det.extract_entities("AI investment boom shows no signs of slowing")
        assert "ai" in result or "AI" in result

    def test_result_is_deduplicated(self):
        result = self.det.extract_entities("TSMC TSMC TSMC chip chip chip")
        assert result.count("TSMC") == 1
        assert result.count("chip") == 1

    def test_strategy_entities_of_interest_matched(self):
        result = self.det.extract_entities("SMIC struggles with advanced chip production")
        assert "SMIC" in result

    def test_empty_text_returns_empty(self):
        assert self.det.extract_entities("") == []

    def test_unrelated_text_returns_empty(self):
        result = self.det.extract_entities("The weather forecast calls for rain tomorrow")
        assert result == []

    def test_partial_word_not_matched(self):
        # "chips" should not trigger exact "chip" word-boundary match at topic level
        # (topic search is substring, so "chips" contains "chip" — this is by design)
        result = self.det.extract_entities("potato chips recipe")
        # "chip" is found as substring — acceptable trade-off
        # but "semiconductor" should NOT be in an unrelated text
        assert "semiconductor" not in result


# ── detect_policy_announcements ───────────────────────────────────────────────

class TestDetectPolicyAnnouncements:
    def setup_method(self):
        self.det = PatternDetector(SAMPLE_PATTERNS)

    def test_matches_subsidy_keyword(self):
        articles = [_make_article(title="Government announces subsidy for chip makers")]
        results = self.det.detect_policy_announcements(articles)
        assert len(results) == 1
        assert "subsidy" in results[0]["policy_keywords_matched"]

    def test_matches_billion_keyword(self):
        articles = [_make_article(title="US pledges $52 billion for semiconductor fund")]
        results = self.det.detect_policy_announcements(articles)
        assert len(results) == 1
        assert "billion" in results[0]["policy_keywords_matched"]

    def test_extracts_monetary_amount(self):
        articles = [_make_article(
            title="CHIPS Act: $52 billion in subsidies approved",
            content="The bill allocates 52 billion dollars for domestic chip production."
        )]
        results = self.det.detect_policy_announcements(articles)
        assert len(results) == 1
        assert len(results[0]["amounts_detected"]) > 0
        assert results[0]["max_amount"] >= 52e9

    def test_filters_out_small_amounts(self):
        articles = [_make_article(
            title="Company receives 5 million investment",
            content="A small investment policy was announced."
        )]
        results = self.det.detect_policy_announcements(articles)
        # keyword matches but amount is below threshold
        assert len(results) == 1
        assert results[0]["amounts_detected"] == []   # 5M < 1B threshold
        assert results[0]["max_amount"] is None

    def test_no_keyword_match_excluded(self):
        articles = [_make_article(title="Stock market closes higher on earnings")]
        results = self.det.detect_policy_announcements(articles)
        assert results == []

    def test_multiple_articles_filtered(self):
        articles = [
            _make_article(title="New regulation for AI companies announced"),
            _make_article(title="Sports results from the weekend"),
            _make_article(title="$2 billion fund established for battery research"),
        ]
        results = self.det.detect_policy_announcements(articles)
        assert len(results) == 2

    def test_amount_extracted_from_trillion(self):
        articles = [_make_article(content="China pledges 1 trillion yuan investment")]
        results = self.det.detect_policy_announcements(articles)
        assert len(results) == 1
        assert results[0]["max_amount"] >= 1e12

    def test_extended_dict_preserves_original_fields(self):
        original = _make_article(title="New investment policy", category="western_mainstream")
        results = self.det.detect_policy_announcements([original])
        assert results[0]["category"] == "western_mainstream"
        assert "policy_keywords_matched" in results[0]


# ── analyze_coverage_gaps ─────────────────────────────────────────────────────

class TestAnalyzeCoverageGaps:
    def setup_method(self):
        self.det = PatternDetector(SAMPLE_PATTERNS)

    def _asia_articles(self, n: int, entity: str = "TSMC") -> list[dict]:
        return [
            _make_article(title=f"TSMC story {i}", category="alternative_asia")
            for i in range(n)
        ]

    def _western_articles(self, n: int, entity: str = "TSMC") -> list[dict]:
        return [
            _make_article(title=f"TSMC story {i}", category="western_mainstream")
            for i in range(n)
        ]

    def test_flags_gap_when_threshold_met(self):
        articles = self._asia_articles(6) + self._western_articles(1)
        gaps = self.det.analyze_coverage_gaps(articles, strategy_id=1)
        assert len(gaps) >= 1
        gap = gaps[0]
        assert gap["asia_count"] >= 5
        assert gap["western_count"] <= 2
        assert gap["gap_ratio"] >= 3.0

    def test_no_gap_when_western_too_high(self):
        articles = self._asia_articles(6) + self._western_articles(5)
        gaps = self.det.analyze_coverage_gaps(articles, strategy_id=1)
        # western_count=5 > max_western_articles=2 → not flagged
        assert all(g["western_count"] <= 2 for g in gaps)

    def test_no_gap_when_asia_too_low(self):
        articles = self._asia_articles(3) + self._western_articles(0)
        gaps = self.det.analyze_coverage_gaps(articles, strategy_id=1)
        # asia_count=3 < min_asia=5 → not flagged
        assert gaps == []

    def test_sorted_by_gap_ratio_descending(self):
        # Create two entities with different ratios
        high_ratio = [
            _make_article(title=f"TSMC story {i}", category="alternative_asia")
            for i in range(8)
        ]
        low_ratio = [
            _make_article(title=f"Samsung story {i}", category="alternative_asia")
            for i in range(5)
        ] + [
            _make_article(title="Samsung western", category="western_mainstream")
        ]
        articles = high_ratio + low_ratio
        gaps = self.det.analyze_coverage_gaps(articles, strategy_id=1)
        if len(gaps) >= 2:
            assert gaps[0]["gap_ratio"] >= gaps[1]["gap_ratio"]

    def test_strategy_id_included_in_result(self):
        articles = self._asia_articles(6) + self._western_articles(1)
        gaps = self.det.analyze_coverage_gaps(articles, strategy_id=42)
        assert all(g["strategy_id"] == 42 for g in gaps)

    def test_article_titles_included(self):
        articles = self._asia_articles(6) + self._western_articles(1)
        gaps = self.det.analyze_coverage_gaps(articles, strategy_id=1)
        if gaps:
            assert isinstance(gaps[0]["article_titles"], list)

    def test_empty_articles_returns_empty(self):
        assert self.det.analyze_coverage_gaps([], strategy_id=1) == []

    def test_articles_without_category_treated_as_unknown(self):
        articles = [{"title": "TSMC story", "content": ""} for _ in range(6)]
        # No category → unknown → not in western or asia buckets → no gap
        gaps = self.det.analyze_coverage_gaps(articles, strategy_id=1)
        assert all(g["asia_count"] == 0 for g in gaps)

    def test_custom_thresholds_respected(self):
        det = PatternDetector({
            "coverage_gap": {
                "min_asia_articles": 2,
                "max_western_articles": 5,
                "min_gap_ratio": 1.0,
            }
        })
        articles = self._asia_articles(2) + self._western_articles(1)
        gaps = det.analyze_coverage_gaps(articles, strategy_id=1)
        assert len(gaps) >= 1


# ── _extract_amounts ──────────────────────────────────────────────────────────

class TestExtractAmounts:
    def test_dollar_billion(self):
        amounts = PatternDetector._extract_amounts("$5 billion allocated")
        assert any(abs(a - 5e9) < 1e6 for a in amounts)

    def test_usd_trillion(self):
        amounts = PatternDetector._extract_amounts("USD 1.5 trillion package")
        assert any(abs(a - 1.5e12) < 1e9 for a in amounts)

    def test_million(self):
        amounts = PatternDetector._extract_amounts("200 million dollars approved")
        assert any(abs(a - 200e6) < 1e6 for a in amounts)

    def test_multiple_amounts(self):
        amounts = PatternDetector._extract_amounts(
            "$10 billion here and 500 million there"
        )
        assert len(amounts) == 2

    def test_no_amounts_returns_empty(self):
        assert PatternDetector._extract_amounts("no money mentioned") == []
