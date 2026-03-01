"""Tests for app.services.scrapers.article_processor."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from app.services.scrapers.article_processor import (
    ArticleProcessor,
    STATUS_SCRAPED_NEW,
    STATUS_ANALYZED_EXISTING,
    STATUS_SKIPPED,
)

# ── Sample pattern rules ──────────────────────────────────────────────────────

SAMPLE_RULES = [
    {
        "name": "sanctions_announcement",
        "description": "New sanctions imposed on a country or sector.",
        "keywords": ["sanctions", "sanctioned", "embargo"],
        "exclude": ["lifted", "removed"],
        "tickers": ["LMT", "RTX"],
        "signal_type": "bullish",
        "confidence": 0.60,
    },
    {
        "name": "defence_spending_increase",
        "description": "Government increase in defence budget.",
        "keywords": ["defence budget", "defense spending", "military aid"],
        "exclude": ["cut", "reduction"],
        "tickers": ["LMT", "NOC"],
        "signal_type": "bullish",
        "confidence": 0.70,
    },
    {
        "name": "tariff_increase",
        "description": "New tariffs hurting import-heavy sectors.",
        "keywords": ["tariff", "tariffs"],
        "exclude": ["removed", "reduced"],
        "tickers": ["WMT"],
        "signal_type": "bearish",
        "confidence": 0.55,
    },
]


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_processor(rules=None):
    return ArticleProcessor("propaganda-arbitrage", rules or SAMPLE_RULES)


def make_mock_db():
    """Return a minimal mock Session."""
    db = MagicMock()
    db.query.return_value = db
    db.filter.return_value = db
    db.first.return_value = None
    db.flush = MagicMock()
    db.add = MagicMock()
    return db


# ── _score_article ────────────────────────────────────────────────────────────

class TestScoreArticle:
    def setup_method(self):
        self.proc = make_processor()

    def test_matching_rule_raises_relevance(self):
        rel, sent, sig, topics = self.proc._score_article(
            "US imposes new sanctions on Iran", "The White House announced sanctions today."
        )
        assert rel > 0.1
        assert "sanctions_announcement" in topics

    def test_no_match_returns_low_relevance(self):
        rel, sent, sig, topics = self.proc._score_article(
            "Apple launches new iPhone", "Consumer electronics product."
        )
        assert rel == 0.1
        assert topics == []

    def test_bullish_signal_gives_positive_sentiment(self):
        _, sent, _, topics = self.proc._score_article(
            "Congress approves defense spending bill", "Military aid increased."
        )
        assert sent > 0
        assert "defence_spending_increase" in topics

    def test_bearish_signal_gives_negative_sentiment(self):
        _, sent, _, _ = self.proc._score_article(
            "White House announces new tariff on imports", "Tariffs raised 25%."
        )
        assert sent < 0

    def test_exclude_keywords_prevent_match(self):
        _, _, _, topics = self.proc._score_article(
            "Sanctions removed from Iran after deal", "Embargo lifted following agreement."
        )
        assert "sanctions_announcement" not in topics

    def test_signal_strength_is_max_confidence(self):
        _, _, sig, topics = self.proc._score_article(
            "US defence spending increase announced with new sanctions",
            "Both defence budget and sanctions were discussed."
        )
        confidences = [r["confidence"] for r in SAMPLE_RULES if r["name"] in topics]
        assert sig == pytest.approx(max(confidences), abs=0.01)

    def test_no_rules_returns_defaults(self):
        proc = ArticleProcessor("test-strategy", pattern_rules=[])
        rel, sent, sig, topics = proc._score_article("any title", "any content")
        assert rel == 0.1
        assert sent == 0.0
        assert sig == 0.0
        assert topics == []


# ── _extract_entities ─────────────────────────────────────────────────────────

class TestExtractEntities:
    def setup_method(self):
        self.proc = make_processor()

    def test_detects_country(self):
        entities = self.proc._extract_entities("Russia faces new sanctions", "")
        assert "russia" in entities["countries"]

    def test_detects_multiple_countries(self):
        entities = self.proc._extract_entities("US and China trade war", "")
        countries = entities["countries"]
        assert "china" in countries
        assert "united states" in countries or "usa" in countries or "us" in countries

    def test_detects_dollar_ticker(self):
        entities = self.proc._extract_entities("$LMT soars on defence news", "")
        assert "LMT" in entities["tickers"]

    def test_no_entities_returns_empty_lists(self):
        entities = self.proc._extract_entities("weather report for tomorrow", "")
        assert entities["countries"] == []

    def test_not_ticker_excluded(self):
        entities = self.proc._extract_entities("THE US CEO announced today", "")
        tickers = entities["tickers"]
        assert "THE" not in tickers
        assert "CEO" not in tickers


# ── _build_thesis_notes ───────────────────────────────────────────────────────

class TestBuildThesisNotes:
    def setup_method(self):
        self.proc = make_processor()

    def test_single_matched_rule(self):
        notes = self.proc._build_thesis_notes(["sanctions_announcement"])
        assert "sanctions" in notes.lower()

    def test_multiple_matched_rules(self):
        notes = self.proc._build_thesis_notes(
            ["sanctions_announcement", "defence_spending_increase"]
        )
        assert "|" in notes

    def test_no_matched_rules_returns_none(self):
        assert self.proc._build_thesis_notes([]) is None

    def test_unknown_rule_name_skipped(self):
        notes = self.proc._build_thesis_notes(["nonexistent_rule"])
        assert notes is None or notes == ""


# ── process_article — status routing ─────────────────────────────────────────

class TestProcessArticleStatusRouting:
    def setup_method(self):
        self.proc = make_processor()

    @patch("app.services.scrapers.article_processor.should_scrape")
    @patch.object(ArticleProcessor, "_store_raw_content", return_value=42)
    @patch.object(ArticleProcessor, "_create_registry_entry", return_value=99)
    @patch.object(ArticleProcessor, "_analyze_and_store")
    def test_new_article_returns_scraped_new(
        self, mock_analyse, mock_create, mock_store, mock_dedup
    ):
        mock_dedup.return_value = (True, None, None)
        db = make_mock_db()

        status, rid = self.proc.process_article(db, "https://ex.com/1", "Title", "body", 1)
        assert status == STATUS_SCRAPED_NEW
        assert rid == 99
        mock_store.assert_called_once()
        mock_create.assert_called_once()
        mock_analyse.assert_called_once()

    @patch("app.services.scrapers.article_processor.should_scrape")
    @patch.object(ArticleProcessor, "_has_existing_analysis", return_value=True)
    def test_already_analysed_returns_skipped(self, mock_has, mock_dedup):
        mock_dedup.return_value = (False, 7, "url_match")
        db = make_mock_db()

        status, rid = self.proc.process_article(db, "https://ex.com/1", "Title", "body", 1)
        assert status == STATUS_SKIPPED
        assert rid == 7

    @patch("app.services.scrapers.article_processor.should_scrape")
    @patch.object(ArticleProcessor, "_has_existing_analysis", return_value=False)
    @patch.object(ArticleProcessor, "_analyze_and_store")
    def test_new_strategy_old_article_returns_analyzed_existing(
        self, mock_analyse, mock_has, mock_dedup
    ):
        mock_dedup.return_value = (False, 7, "content_match")
        db = make_mock_db()

        status, rid = self.proc.process_article(db, "https://ex.com/1", "Title", "body", 2)
        assert status == STATUS_ANALYZED_EXISTING
        assert rid == 7
        mock_analyse.assert_called_once()

    @patch("app.services.scrapers.article_processor.should_scrape")
    def test_dedup_miss_with_none_registry_id_returns_skipped(self, mock_dedup):
        mock_dedup.return_value = (False, None, "url_match")
        db = make_mock_db()

        status, rid = self.proc.process_article(db, "https://ex.com/1", "Title", "body", 1)
        assert status == STATUS_SKIPPED
        assert rid is None


# ── process_article — pipeline integration ────────────────────────────────────

class TestProcessArticlePipeline:
    def setup_method(self):
        self.proc = make_processor()

    @patch("app.services.scrapers.article_processor.should_scrape")
    @patch.object(ArticleProcessor, "_store_raw_content", return_value=1)
    @patch.object(ArticleProcessor, "_create_registry_entry", return_value=10)
    @patch.object(ArticleProcessor, "_analyze_and_store")
    def test_content_preview_truncated_for_dedup(
        self, mock_analyse, mock_create, mock_store, mock_dedup
    ):
        mock_dedup.return_value = (True, None, None)
        long_content = "a" * 2000
        db = make_mock_db()

        self.proc.process_article(db, "https://ex.com/1", "T", long_content, 1)
        # should_scrape should receive content[:500]
        _, call_args, _ = mock_dedup.mock_calls[0]
        assert len(call_args[3]) == 500

    @patch("app.services.scrapers.article_processor.should_scrape")
    @patch.object(ArticleProcessor, "_store_raw_content", return_value=5)
    @patch.object(ArticleProcessor, "_create_registry_entry", return_value=20)
    @patch.object(ArticleProcessor, "_analyze_and_store")
    def test_published_at_forwarded_to_store(
        self, mock_analyse, mock_create, mock_store, mock_dedup
    ):
        mock_dedup.return_value = (True, None, None)
        pub = datetime(2024, 1, 15, tzinfo=timezone.utc)
        db = make_mock_db()

        self.proc.process_article(db, "https://ex.com", "T", "body", 1, published_at=pub)
        _, kwargs = mock_store.call_args
        # published_at passed as keyword or positional 4th arg
        call_positional = mock_store.call_args[0]
        assert pub in call_positional


# ── _store_raw_content ────────────────────────────────────────────────────────

class TestStoreRawContent:
    def test_creates_sqlite_and_returns_int(self, tmp_path):
        """Integration test against a real temporary SQLite file."""
        proc = ArticleProcessor("test-strategy")
        # Override the DB path to use tmp_path
        proc._db_path = tmp_path / "test-strategy.db"
        # Ensure the data dir exists
        proc._db_path.parent.mkdir(parents=True, exist_ok=True)

        row_id = proc._store_raw_content(
            "https://example.com/1",
            "Test Title",
            "Test content body",
            datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_second_insert_increments_id(self, tmp_path):
        proc = ArticleProcessor("test-strategy")
        proc._db_path = tmp_path / "test-strategy.db"
        proc._db_path.parent.mkdir(parents=True, exist_ok=True)

        id1 = proc._store_raw_content("https://example.com/1", "T1", "body", None)
        id2 = proc._store_raw_content("https://example.com/2", "T2", "body", None)
        assert id2 > id1
