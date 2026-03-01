"""Tests for the three-tier deduplication system in app.utils.dedup."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from app.utils.dedup import (
    FUZZY_LOOKBACK_HOURS,
    FUZZY_THRESHOLD,
    content_fingerprint,
    fuzzy_title_similarity,
    register_alias,
    should_scrape,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_registry(id: int, url: str, title: str | None = None, content_hash: str | None = None):
    """Return a mock ArticleRegistry-like object."""
    rec = MagicMock()
    rec.id = id
    rec.url = url
    rec.title = title
    rec.content_hash = content_hash
    rec.scrape_count = 1
    rec.last_seen_at = datetime.now(timezone.utc)
    return rec


def _mock_db(
    registry_by_url=None,
    alias_by_url=None,
    registry_by_hash=None,
    recent_articles=None,
):
    """Build a mock Session whose query chains return the supplied fixtures."""
    db = MagicMock()

    def _make_chain(first_val, all_val=None):
        chain = MagicMock()
        chain.filter.return_value = chain
        chain.filter_by.return_value = chain
        chain.first.return_value = first_val
        chain.all.return_value = all_val if all_val is not None else (
            [first_val] if first_val is not None else []
        )
        return chain

    # We intercept db.query(Model) and return the appropriate chain.
    # Import lazily to avoid circular imports during collection.
    def query_side_effect(model):
        name = getattr(model, "__name__", str(model))
        if name == "ArticleRegistry":
            # Layer 1 url lookup → Layer 2 hash lookup → Layer 3 recent
            # Each call to db.query(ArticleRegistry) returns a fresh chain.
            # We use a counter on the side_effect closure to track calls.
            query_side_effect.registry_calls = getattr(
                query_side_effect, "registry_calls", 0
            )
            query_side_effect.registry_calls += 1
            call_n = query_side_effect.registry_calls

            if call_n == 1:
                return _make_chain(registry_by_url)
            elif call_n == 2:
                return _make_chain(registry_by_hash)
            else:
                # Layer 3 — return list of recent articles
                chain = _make_chain(None, all_val=recent_articles or [])
                return chain

        elif name == "ArticleUrlAlias":
            return _make_chain(alias_by_url)

        return _make_chain(None)

    db.query.side_effect = query_side_effect
    db.get.return_value = None  # overridden per test when needed
    return db


# ── content_fingerprint ───────────────────────────────────────────────────────

class TestContentFingerprint:
    def test_returns_32_char_hex(self):
        result = content_fingerprint("Some Title", "Some content body here")
        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_inputs_same_hash(self):
        assert (
            content_fingerprint("Title", "body text")
            == content_fingerprint("Title", "body text")
        )

    def test_different_titles_different_hash(self):
        assert (
            content_fingerprint("Title A", "same body")
            != content_fingerprint("Title B", "same body")
        )

    def test_different_bodies_different_hash(self):
        assert (
            content_fingerprint("same title", "body A")
            != content_fingerprint("same title", "body B")
        )

    def test_case_insensitive(self):
        """Normalisation makes case differences invisible."""
        assert (
            content_fingerprint("TITLE", "BODY")
            == content_fingerprint("title", "body")
        )

    def test_punctuation_insensitive(self):
        assert (
            content_fingerprint("Title!", "body, with punctuation.")
            == content_fingerprint("Title", "body  with punctuation")
        )

    def test_only_first_500_chars_of_body_used(self):
        short = "x" * 400
        with_extra = "x" * 400 + "different_suffix_after_500"
        # Both truncate to the same 500-char prefix
        assert (
            content_fingerprint("T", short)
            == content_fingerprint("T", with_extra)
        )

    def test_body_beyond_500_chars_is_ignored(self):
        base = "a" * 500
        assert (
            content_fingerprint("T", base)
            == content_fingerprint("T", base + "extra content here")
        )


# ── fuzzy_title_similarity ────────────────────────────────────────────────────

class TestFuzzyTitleSimilarity:
    def test_identical_titles(self):
        assert fuzzy_title_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        score = fuzzy_title_similarity("sanctions on russia", "apple earnings beat")
        assert score < FUZZY_THRESHOLD

    def test_above_threshold_near_duplicates(self):
        a = "US imposes new sanctions on Russian oil companies"
        b = "US imposes new sanctions on Russian energy companies"
        assert fuzzy_title_similarity(a, b) >= FUZZY_THRESHOLD

    def test_below_threshold_different_topic(self):
        a = "US imposes new sanctions on Russian oil companies"
        b = "Fed raises interest rates by 25 basis points"
        assert fuzzy_title_similarity(a, b) < FUZZY_THRESHOLD

    def test_case_insensitive(self):
        assert fuzzy_title_similarity("HELLO WORLD", "hello world") == 1.0

    def test_punctuation_insensitive(self):
        score = fuzzy_title_similarity("hello, world!", "hello world")
        assert score >= 0.9

    def test_extra_words_reduce_score(self):
        a = "short"
        b = "short title with many many many many extra words appended"
        assert fuzzy_title_similarity(a, b) < 1.0

    def test_symmetric(self):
        a = "sanctions on iran"
        b = "iran sanctions imposed"
        assert fuzzy_title_similarity(a, b) == fuzzy_title_similarity(b, a)

    @pytest.mark.parametrize("similarity,expected_dup", [
        (0.95, True),
        (0.85, True),   # exactly at threshold
        (0.84, False),  # just below threshold
        (0.50, False),
    ])
    def test_threshold_boundary(self, similarity, expected_dup):
        assert (similarity >= FUZZY_THRESHOLD) == expected_dup


# ── register_alias ────────────────────────────────────────────────────────────

class TestRegisterAlias:
    # ArticleUrlAlias is imported locally inside register_alias(), so we patch
    # it at its source module, not at app.utils.dedup.
    def test_adds_alias_to_session(self):
        db = MagicMock()
        with patch("app.models.article.ArticleUrlAlias") as MockAlias:
            mock_instance = MagicMock()
            MockAlias.return_value = mock_instance
            register_alias(db, "https://example.com/dup", 42, "content_match")

        MockAlias.assert_called_once_with(
            url="https://example.com/dup",
            canonical_registry_id=42,
            match_type="content_match",
        )
        db.add.assert_called_once_with(mock_instance)

    def test_does_not_commit(self):
        db = MagicMock()
        with patch("app.models.article.ArticleUrlAlias"):
            register_alias(db, "https://example.com/x", 1, "url_match")
        db.commit.assert_not_called()


# ── should_scrape ─────────────────────────────────────────────────────────────

class TestShouldScrapeLayer1Url:
    def test_new_url_returns_true(self):
        db = _mock_db()
        result = should_scrape(db, "https://example.com/new", "Title", "body")
        assert result == (True, None, None)

    def test_existing_url_returns_false(self):
        existing = _make_registry(id=7, url="https://example.com/article")
        db = _mock_db(registry_by_url=existing)
        ok, rid, match = should_scrape(
            db, "https://example.com/article", "Title", "body"
        )
        assert ok is False
        assert rid == 7
        assert match == "url_match"

    def test_existing_url_bumps_scrape_count(self):
        existing = _make_registry(id=7, url="https://example.com/article")
        existing.scrape_count = 3
        db = _mock_db(registry_by_url=existing)
        should_scrape(db, "https://example.com/article", "Title", "body")
        assert existing.scrape_count == 4

    def test_url_normalised_before_lookup(self):
        """Tracking-param URL should match the clean canonical in the DB."""
        canonical = _make_registry(id=1, url="https://example.com/article")
        db = _mock_db(registry_by_url=canonical)
        ok, rid, match = should_scrape(
            db,
            "https://example.com/article?utm_source=twitter",
            "Title",
            "body",
        )
        assert ok is False
        assert rid == 1
        assert match == "url_match"

    def test_alias_url_hit_returns_url_match(self):
        alias = MagicMock()
        alias.canonical_registry_id = 99
        canonical = _make_registry(id=99, url="https://example.com/original")
        db = _mock_db(registry_by_url=None, alias_by_url=alias)
        db.get.return_value = canonical

        ok, rid, match = should_scrape(
            db, "https://example.com/alias-url", "Title", "body"
        )
        assert ok is False
        assert rid == 99
        assert match == "url_match"


class TestShouldScrapeLayer2Content:
    def test_content_hash_match_returns_content_match(self):
        fp = content_fingerprint("Title", "body text here")
        hash_rec = _make_registry(id=5, url="https://other.com/article")
        hash_rec.content_hash = fp
        db = _mock_db(registry_by_url=None, registry_by_hash=hash_rec)

        ok, rid, match = should_scrape(db, "https://new.com/copy", "Title", "body text here")
        assert ok is False
        assert rid == 5
        assert match == "content_match"

    def test_content_match_registers_alias(self):
        fp = content_fingerprint("T", "body")
        hash_rec = _make_registry(id=5, url="https://other.com/article")
        hash_rec.content_hash = fp
        db = _mock_db(registry_by_url=None, registry_by_hash=hash_rec)

        with patch("app.utils.dedup.register_alias") as mock_alias:
            should_scrape(db, "https://new.com/copy", "T", "body")
            mock_alias.assert_called_once()
            _, called_url, called_id, called_type = mock_alias.call_args[0]
            assert called_id == 5
            assert called_type == "content_match"


class TestShouldScrapeLayer3Fuzzy:
    def test_similar_title_within_24h_returns_fuzzy_match(self):
        recent = _make_registry(
            id=3,
            url="https://example.com/original",
            title="US imposes new sanctions on Russian oil companies",
        )
        recent.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=1)

        db = _mock_db(
            registry_by_url=None,
            registry_by_hash=None,
            recent_articles=[recent],
        )

        ok, rid, match = should_scrape(
            db,
            "https://example.com/copy",
            "US imposes new sanctions on Russian energy companies",
            "different body entirely so hash misses",
        )
        assert ok is False
        assert rid == 3
        assert match == "fuzzy_match"

    def test_different_title_within_24h_returns_new(self):
        recent = _make_registry(
            id=3,
            url="https://example.com/original",
            title="Fed raises interest rates",
        )
        db = _mock_db(
            registry_by_url=None,
            registry_by_hash=None,
            recent_articles=[recent],
        )

        ok, rid, match = should_scrape(
            db,
            "https://example.com/new",
            "Apple reports record quarterly earnings",
            "completely unrelated body text",
        )
        assert ok is True
        assert rid is None
        assert match is None

    def test_fuzzy_match_registers_alias(self):
        recent = _make_registry(
            id=3,
            url="https://example.com/original",
            title="US imposes new sanctions on Russian oil companies",
        )
        db = _mock_db(
            registry_by_url=None,
            registry_by_hash=None,
            recent_articles=[recent],
        )

        with patch("app.utils.dedup.register_alias") as mock_alias:
            should_scrape(
                db,
                "https://example.com/copy",
                "US imposes new sanctions on Russian energy companies",
                "different body",
            )
            mock_alias.assert_called_once()
            _, _, called_id, called_type = mock_alias.call_args[0]
            assert called_id == 3
            assert called_type == "fuzzy_match"

    def test_empty_title_skips_fuzzy_layer(self):
        """If title is empty, Layer 3 should not run and we get a new article."""
        recent = _make_registry(
            id=3, url="https://example.com/original", title="Some title"
        )
        db = _mock_db(
            registry_by_url=None,
            registry_by_hash=None,
            recent_articles=[recent],
        )
        ok, rid, match = should_scrape(db, "https://example.com/new", "", "body")
        assert ok is True

    def test_candidate_with_no_title_skipped(self):
        """Registry entries with no title must not cause a crash in L3."""
        no_title = _make_registry(id=9, url="https://example.com/notitle")
        no_title.title = None
        db = _mock_db(
            registry_by_url=None,
            registry_by_hash=None,
            recent_articles=[no_title],
        )
        ok, rid, match = should_scrape(
            db, "https://example.com/new", "Some real title", "body"
        )
        assert ok is True
