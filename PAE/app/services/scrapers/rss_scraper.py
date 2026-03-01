"""RSS/Atom feed scraper with retry logic and multi-format date parsing."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser  # type: ignore[import-untyped]
import requests

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = (1, 3, 7)   # seconds between attempts (exponential-ish)
_FETCH_TIMEOUT = 15          # seconds per HTTP request


class ScraperError(Exception):
    """Raised when a feed cannot be fetched after all retries."""


class RSSNewsScraper:
    """Fetch and normalise entries from RSS 2.0 and Atom feeds.

    Args:
        timeout: Per-request HTTP timeout in seconds.
        max_retries: Number of fetch attempts before raising ``ScraperError``.
        user_agent: ``User-Agent`` header sent with every request.
    """

    def __init__(
        self,
        timeout: int = _FETCH_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
        user_agent: str = "PAE-Bot/1.0 (Propaganda Arbitrage Engine)",
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})

    # ── Public API ────────────────────────────────────────────────────────────

    def scrape_feed(self, feed_url: str) -> list[dict]:
        """Fetch a single RSS/Atom feed and return a list of article dicts.

        Each returned dict contains:
        ``url``, ``title``, ``content``, ``summary``, ``published_at``,
        ``source_url``, ``feed_name``, ``authors``, ``tags``.

        Returns an empty list on parse failure (logged at WARNING).
        """
        raw = self._fetch_with_retry(feed_url)
        feed_name: str = raw.feed.get("title", feed_url)

        articles: list[dict] = []
        for entry in raw.get("entries", []):
            try:
                article = self._entry_to_article(entry, feed_url, feed_name)
                articles.append(article)
            except Exception:
                logger.warning("Failed to parse entry from %s — skipping", feed_url, exc_info=True)

        logger.info("Scraped %d articles from %s", len(articles), feed_url)
        return articles

    def scrape_multiple(self, feed_urls: list[str]) -> list[dict]:
        """Fetch multiple feeds, returning a deduplicated combined list.

        Feeds are fetched sequentially.  Failures on individual feeds are
        logged but do not abort the remaining feeds.

        Args:
            feed_urls: List of RSS/Atom feed URLs.

        Returns:
            Combined list of article dicts, deduplicated by URL.
        """
        seen_urls: set[str] = set()
        results: list[dict] = []

        for url in feed_urls:
            try:
                articles = self.scrape_feed(url)
            except ScraperError:
                logger.error("Skipping feed after all retries failed: %s", url)
                continue

            for article in articles:
                article_url = article.get("url", "")
                if article_url and article_url not in seen_urls:
                    seen_urls.add(article_url)
                    results.append(article)
                elif not article_url:
                    results.append(article)

        logger.info("scrape_multiple: %d unique articles from %d feeds", len(results), len(feed_urls))
        return results

    def parse_date(self, date_value: Any) -> datetime | None:
        """Parse a date from any common feedparser representation.

        Handles:
        - ``time.struct_time`` (feedparser's ``published_parsed`` / ``updated_parsed``)
        - RFC 2822 strings (``"Mon, 02 Jan 2006 15:04:05 +0000"``)
        - ISO 8601 strings (``"2024-01-15T10:30:00Z"``, ``"2024-01-15T10:30:00+00:00"``)
        - ``None`` / unrecognised values → returns ``None``

        All returned datetimes are timezone-aware UTC.
        """
        if date_value is None:
            return None

        # feedparser gives us time.struct_time (always UTC)
        if hasattr(date_value, "tm_year"):
            try:
                return datetime(*date_value[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                return None

        if not isinstance(date_value, str):
            return None

        date_str = date_value.strip()

        # RFC 2822 (email-style)
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        # ISO 8601 / RFC 3339 variants
        for fmt in (
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S+00:00",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        # Python 3.11+ fromisoformat handles most ISO variants
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass

        logger.debug("Could not parse date string: %r", date_str)
        return None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _fetch_with_retry(self, url: str) -> feedparser.FeedParserDict:
        """Fetch the feed URL with retry logic.

        Feedparser can parse directly from a URL, but we use requests first so
        we can apply timeout, retries, and custom headers, then pass the raw
        text to feedparser for parsing.

        Raises:
            ScraperError: After all retry attempts are exhausted.
        """
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)

                if feed.bozo and feed.bozo_exception and not feed.entries:
                    # feedparser signals a parse error but no content at all
                    raise ScraperError(
                        f"feedparser bozo error for {url}: {feed.bozo_exception}"
                    )

                return feed

            except (requests.RequestException, ScraperError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
                    logger.warning(
                        "Feed fetch attempt %d/%d failed for %s (%s) — retrying in %ds",
                        attempt, self.max_retries, url, exc, delay,
                    )
                    time.sleep(delay)

        raise ScraperError(
            f"Failed to fetch {url} after {self.max_retries} attempts"
        ) from last_exc

    def _extract_content(self, entry: Any) -> str:
        """Return the best available body text from a feedparser entry.

        Priority:
        1. ``content`` list (Atom / full-text feeds)
        2. ``summary`` (most RSS 2.0 feeds)
        3. ``description`` (older RSS 1.0)
        """
        content_list = entry.get("content", [])
        if content_list:
            return content_list[0].get("value", "")
        return entry.get("summary", "") or entry.get("description", "") or ""

    def _entry_to_article(self, entry: Any, source_url: str, feed_name: str) -> dict:
        """Normalise a feedparser entry into a flat article dict."""
        # Prefer published_parsed; fall back to updated_parsed, then raw strings
        date_value = (
            entry.get("published_parsed")
            or entry.get("updated_parsed")
            or entry.get("published")
            or entry.get("updated")
        )
        published_at = self.parse_date(date_value)

        # Authors: list of name strings
        authors: list[str] = []
        for author in entry.get("authors", []):
            name = author.get("name", "").strip()
            if name:
                authors.append(name)
        if not authors and entry.get("author"):
            authors = [entry["author"]]

        # Tags / categories
        tags: list[str] = [
            tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term")
        ]

        content = self._extract_content(entry)
        url = entry.get("link", "").strip()

        return {
            "url": url,
            "title": (entry.get("title") or "").strip(),
            "content": content,
            "summary": (entry.get("summary") or content)[:500],
            "published_at": published_at,
            "source_url": source_url,
            "feed_name": feed_name,
            "authors": authors,
            "tags": tags,
        }
