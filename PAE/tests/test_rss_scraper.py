"""Tests for app.services.scrapers.rss_scraper."""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.scrapers.rss_scraper import RSSNewsScraper, ScraperError


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _make_entry(
    title="Test Article",
    link="https://example.com/article",
    summary="Article summary here",
    published_parsed=None,
    content=None,
    authors=None,
    tags=None,
):
    entry = MagicMock()
    entry.get = lambda k, default=None: {
        "title": title,
        "link": link,
        "summary": summary,
        "published_parsed": published_parsed,
        "updated_parsed": None,
        "published": None,
        "updated": None,
        "content": content or [],
        "authors": authors or [],
        "author": "",
        "tags": tags or [],
        "description": "",
    }.get(k, default)
    return entry


def _make_feed(entries=None, feed_title="Test Feed", bozo=False, bozo_exception=None):
    feed_obj = MagicMock()
    feed_obj.get = lambda k, d=None: {
        "entries": entries or [],
        "feed": MagicMock(get=lambda k, d=None: {"title": feed_title}.get(k, d)),
    }.get(k, d)
    feed_obj.feed = MagicMock()
    feed_obj.feed.get = lambda k, d=None: {"title": feed_title}.get(k, d)
    feed_obj.entries = entries or []
    feed_obj.bozo = bozo
    feed_obj.bozo_exception = bozo_exception
    return feed_obj


def _make_response(text="<rss/>", status_code=200):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


# ── parse_date ────────────────────────────────────────────────────────────────

class TestParseDate:
    def setup_method(self):
        self.scraper = RSSNewsScraper()

    def test_struct_time_parsed(self):
        st = time.strptime("2024-01-15 10:30:00", "%Y-%m-%d %H:%M:%S")
        result = self.scraper.parse_date(st)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_none_returns_none(self):
        assert self.scraper.parse_date(None) is None

    def test_rfc2822_string(self):
        result = self.scraper.parse_date("Mon, 15 Jan 2024 10:30:00 +0000")
        assert result is not None
        assert result.year == 2024
        assert result.tzinfo is not None

    def test_iso8601_z_suffix(self):
        result = self.scraper.parse_date("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.hour == 10

    def test_iso8601_offset(self):
        result = self.scraper.parse_date("2024-01-15T10:30:00+00:00")
        assert result is not None
        assert result.year == 2024

    def test_date_only_string(self):
        result = self.scraper.parse_date("2024-01-15")
        assert result is not None
        assert result.year == 2024
        assert result.tzinfo == timezone.utc

    def test_unrecognised_string_returns_none(self):
        assert self.scraper.parse_date("not-a-date") is None

    def test_non_string_non_struct_returns_none(self):
        assert self.scraper.parse_date(12345) is None

    def test_result_is_always_utc(self):
        result = self.scraper.parse_date("Mon, 15 Jan 2024 10:30:00 +0500")
        assert result is not None
        assert result.tzinfo == timezone.utc
        assert result.hour == 5  # 10:30 +0500 → 05:30 UTC


# ── _extract_content ──────────────────────────────────────────────────────────

class TestExtractContent:
    def setup_method(self):
        self.scraper = RSSNewsScraper()

    def _entry(self, content=None, summary=None, description=None):
        e = MagicMock()
        e.get = lambda k, d=None: {
            "content": content or [],
            "summary": summary or "",
            "description": description or "",
        }.get(k, d)
        return e

    def test_atom_content_list_takes_priority(self):
        e = self._entry(content=[{"value": "full body text"}], summary="short summary")
        assert self.scraper._extract_content(e) == "full body text"

    def test_falls_back_to_summary(self):
        e = self._entry(content=[], summary="rss summary")
        assert self.scraper._extract_content(e) == "rss summary"

    def test_falls_back_to_description(self):
        e = self._entry(content=[], summary="", description="rss description")
        assert self.scraper._extract_content(e) == "rss description"

    def test_returns_empty_string_when_nothing(self):
        e = self._entry()
        assert self.scraper._extract_content(e) == ""


# ── _entry_to_article ─────────────────────────────────────────────────────────

class TestEntryToArticle:
    def setup_method(self):
        self.scraper = RSSNewsScraper()

    def test_basic_fields_populated(self):
        st = time.strptime("2024-01-15 10:30:00", "%Y-%m-%d %H:%M:%S")
        entry = _make_entry(
            title="Sanctions on Russia",
            link="https://reuters.com/article",
            summary="US imposes new sanctions",
            published_parsed=st,
        )
        article = self.scraper._entry_to_article(entry, "https://reuters.com/rss", "Reuters")
        assert article["title"] == "Sanctions on Russia"
        assert article["url"] == "https://reuters.com/article"
        assert article["feed_name"] == "Reuters"
        assert article["source_url"] == "https://reuters.com/rss"
        assert isinstance(article["published_at"], datetime)

    def test_summary_truncated_to_500_chars(self):
        long_summary = "x" * 1000
        entry = _make_entry(summary=long_summary)
        article = self.scraper._entry_to_article(entry, "", "")
        assert len(article["summary"]) <= 500

    def test_tags_extracted(self):
        tag1 = MagicMock()
        tag1.get = lambda k, d=None: {"term": "sanctions"}.get(k, d)
        tag2 = MagicMock()
        tag2.get = lambda k, d=None: {"term": "russia"}.get(k, d)
        entry = _make_entry(tags=[tag1, tag2])
        article = self.scraper._entry_to_article(entry, "", "")
        assert "sanctions" in article["tags"]
        assert "russia" in article["tags"]

    def test_authors_extracted(self):
        author = MagicMock()
        author.get = lambda k, d=None: {"name": "Jane Doe"}.get(k, d)
        entry = _make_entry(authors=[author])
        article = self.scraper._entry_to_article(entry, "", "")
        assert "Jane Doe" in article["authors"]

    def test_no_published_date_returns_none(self):
        entry = _make_entry(published_parsed=None)
        article = self.scraper._entry_to_article(entry, "", "")
        assert article["published_at"] is None


# ── scrape_feed ───────────────────────────────────────────────────────────────

class TestScrapeFeed:
    def setup_method(self):
        self.scraper = RSSNewsScraper(max_retries=1)

    @patch("app.services.scrapers.rss_scraper.feedparser.parse")
    @patch("app.services.scrapers.rss_scraper.requests.Session.get")
    def test_returns_article_list(self, mock_get, mock_feedparse):
        mock_get.return_value = _make_response("<rss/>")
        entry = _make_entry("Article One", "https://example.com/1")
        mock_feedparse.return_value = _make_feed(entries=[entry])

        articles = self.scraper.scrape_feed("https://example.com/feed")
        assert len(articles) == 1
        assert articles[0]["title"] == "Article One"

    @patch("app.services.scrapers.rss_scraper.feedparser.parse")
    @patch("app.services.scrapers.rss_scraper.requests.Session.get")
    def test_empty_feed_returns_empty_list(self, mock_get, mock_feedparse):
        mock_get.return_value = _make_response()
        mock_feedparse.return_value = _make_feed(entries=[])

        articles = self.scraper.scrape_feed("https://example.com/empty")
        assert articles == []

    @patch("app.services.scrapers.rss_scraper.feedparser.parse")
    @patch("app.services.scrapers.rss_scraper.requests.Session.get")
    def test_bad_entry_skipped_not_raised(self, mock_get, mock_feedparse):
        mock_get.return_value = _make_response()
        bad_entry = MagicMock()
        bad_entry.get.side_effect = RuntimeError("boom")
        good_entry = _make_entry("Good", "https://example.com/good")
        mock_feedparse.return_value = _make_feed(entries=[bad_entry, good_entry])

        articles = self.scraper.scrape_feed("https://example.com/feed")
        assert len(articles) == 1
        assert articles[0]["title"] == "Good"

    @patch("app.services.scrapers.rss_scraper.requests.Session.get")
    def test_http_error_raises_scraper_error(self, mock_get):
        import requests as req
        mock_get.return_value = _make_response(status_code=503)
        with pytest.raises(ScraperError):
            self.scraper.scrape_feed("https://example.com/feed")


# ── scrape_multiple ───────────────────────────────────────────────────────────

class TestScrapeMultiple:
    def setup_method(self):
        self.scraper = RSSNewsScraper(max_retries=1)

    def test_deduplicates_by_url(self):
        article = {"url": "https://example.com/1", "title": "A"}

        with patch.object(self.scraper, "scrape_feed", return_value=[article]):
            results = self.scraper.scrape_multiple(
                ["https://feed1.com", "https://feed2.com"]
            )
        assert len(results) == 1

    def test_combines_unique_articles(self):
        a1 = {"url": "https://example.com/1", "title": "A"}
        a2 = {"url": "https://example.com/2", "title": "B"}

        def fake_scrape(url):
            return [a1] if "feed1" in url else [a2]

        with patch.object(self.scraper, "scrape_feed", side_effect=fake_scrape):
            results = self.scraper.scrape_multiple(
                ["https://feed1.com", "https://feed2.com"]
            )
        assert len(results) == 2

    def test_failed_feed_skipped(self):
        good = {"url": "https://example.com/ok", "title": "OK"}

        def fake_scrape(url):
            if "bad" in url:
                raise ScraperError("timeout")
            return [good]

        with patch.object(self.scraper, "scrape_feed", side_effect=fake_scrape):
            results = self.scraper.scrape_multiple(
                ["https://bad-feed.com", "https://good-feed.com"]
            )
        assert len(results) == 1
        assert results[0]["title"] == "OK"
