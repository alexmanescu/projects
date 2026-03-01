"""Article processing pipeline: dedup → raw storage → registry → analysis."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.utils.dedup import content_fingerprint, should_scrape
from app.utils.url_normalizer import normalize_url

logger = logging.getLogger(__name__)

# ── Raw content storage (SQLite per strategy) ─────────────────────────────────

_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"

_CREATE_ARTICLES_TABLE = """
CREATE TABLE IF NOT EXISTS articles (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    url       TEXT    NOT NULL,
    title     TEXT,
    content   TEXT,
    scraped_at TEXT   NOT NULL
)
"""

# ── Entity extraction constants ───────────────────────────────────────────────

_COUNTRIES: frozenset[str] = frozenset(
    {
        "russia", "china", "iran", "ukraine", "israel", "taiwan", "north korea",
        "south korea", "japan", "germany", "france", "uk", "britain", "england",
        "india", "pakistan", "saudi arabia", "turkey", "venezuela", "cuba",
        "syria", "iraq", "afghanistan", "libya", "sudan", "ethiopia", "myanmar",
        "belarus", "serbia", "hungary", "poland", "brazil", "mexico", "canada",
        "australia", "united states", "usa", "europe", "european union", "nato",
        "opec", "g7", "g20",
    }
)

# Matches $TICKER or standalone UPPER words 2-5 chars (heuristic)
_TICKER_RE = re.compile(r'\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\b')

# Common non-ticker uppercase acronyms to exclude from ticker extraction
_NOT_TICKERS: frozenset[str] = frozenset(
    {
        "US", "EU", "UK", "UN", "NATO", "FED", "GDP", "CEO", "CFO", "IPO",
        "ETF", "ESG", "AI", "IT", "HR", "PR", "DC", "NY", "LA", "PM", "AM",
        "THE", "AND", "FOR", "WITH", "FROM", "THAT", "THIS", "HAVE", "WILL",
        "BEEN", "WERE", "THEY", "SAID", "ALSO", "MORE", "OVER", "THAN",
        "RSS", "HTML", "HTTP", "HTTPS", "API", "PDF", "FAQ",
    }
)


# ── Result status constants ───────────────────────────────────────────────────

STATUS_SCRAPED_NEW = "scraped_new"
STATUS_ANALYZED_EXISTING = "analyzed_existing"
STATUS_SKIPPED = "skipped"


class ArticleProcessor:
    """Orchestrates the full article pipeline for a single strategy.

    Args:
        strategy_name: Slug of the strategy (e.g. ``"propaganda-arbitrage"``).
        pattern_rules: List of pattern rule dicts from the strategy's
            ``pattern_rules.py``.  Used for rule-based relevance scoring.
            Pass ``[]`` to skip rule matching.
    """

    def __init__(
        self,
        strategy_name: str,
        pattern_rules: list[dict] | None = None,
    ) -> None:
        self.strategy_name = strategy_name
        self.pattern_rules = pattern_rules or []
        self._db_path = _DATA_DIR / f"{strategy_name}.db"

    # ── Public API ────────────────────────────────────────────────────────────

    def process_article(
        self,
        db: Session,
        url: str,
        title: str,
        content: str,
        strategy_id: int,
        published_at: datetime | None = None,
    ) -> tuple[str, int | None]:
        """Run one article through the full dedup → store → analyse pipeline.

        Args:
            db: Active SQLAlchemy session (caller commits after return).
            url: Raw article URL.
            title: Article headline.
            content: Full body text.
            strategy_id: ``strategies.id`` in the main DB.
            published_at: Original publication timestamp (optional).

        Returns:
            A ``(status, registry_id)`` tuple where status is one of:

            - ``'scraped_new'``         — new article, fully processed
            - ``'analyzed_existing'``   — known article, new strategy analysis added
            - ``'skipped'``             — already fully processed, nothing to do
        """
        # ── Step 1: Three-tier dedup check ────────────────────────────────────
        do_scrape, registry_id, match_type = should_scrape(
            db, url, title, content[:500]
        )

        if not do_scrape:
            logger.debug(
                "Dedup hit [%s] registry_id=%s url=%s", match_type, registry_id, url
            )
            if registry_id and self._has_existing_analysis(db, registry_id, strategy_id):
                return STATUS_SKIPPED, registry_id

            # Known article, but this strategy hasn't analysed it yet
            if registry_id:
                self._analyze_and_store(db, title, content, registry_id, strategy_id)
                return STATUS_ANALYZED_EXISTING, registry_id

            return STATUS_SKIPPED, registry_id

        # ── Step 2: Store raw content in strategy SQLite ───────────────────────
        content_id = self._store_raw_content(url, title, content, published_at)

        # ── Step 3: Create registry entry in main DB ──────────────────────────
        c_hash = content_fingerprint(title, content[:500])
        registry_id = self._create_registry_entry(
            db, url, title, c_hash, content_id, strategy_id
        )

        # ── Step 4: Run analysis and store results ────────────────────────────
        self._analyze_and_store(db, title, content, registry_id, strategy_id)

        logger.info("Processed new article registry_id=%s url=%s", registry_id, url)
        return STATUS_SCRAPED_NEW, registry_id

    # ── Internal: raw content storage ─────────────────────────────────────────

    def _store_raw_content(
        self,
        url: str,
        title: str,
        content: str,
        published_at: datetime | None,
    ) -> int:
        """Insert into strategy-specific SQLite DB; return the new row ID."""
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(_CREATE_ARTICLES_TABLE)
            cur = conn.execute(
                "INSERT INTO articles (url, title, content, scraped_at) VALUES (?, ?, ?, ?)",
                (
                    normalize_url(url),
                    title,
                    content,
                    (published_at or datetime.now(timezone.utc)).isoformat(),
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # ── Internal: registry management ─────────────────────────────────────────

    def _create_registry_entry(
        self,
        db: Session,
        url: str,
        title: str,
        c_hash: str,
        content_id: int,
        strategy_id: int,
    ) -> int:
        """Insert into ``article_registry`` and return the new ``id``."""
        from app.models.article import ArticleRegistry

        entry = ArticleRegistry(
            url=normalize_url(url),
            title=title[:500] if title else None,
            content_db=self.strategy_name,
            content_table="articles",
            content_id=content_id,
            content_hash=c_hash,
            first_scraped_by=strategy_id,
        )
        db.add(entry)
        db.flush()   # populate entry.id without full commit
        return entry.id

    def _has_existing_analysis(
        self, db: Session, registry_id: int, strategy_id: int
    ) -> bool:
        """Return True if ``article_analysis`` already has a row for this pair."""
        from app.models.article import ArticleAnalysis

        return (
            db.query(ArticleAnalysis)
            .filter(
                ArticleAnalysis.registry_id == registry_id,
                ArticleAnalysis.strategy_id == strategy_id,
            )
            .first()
        ) is not None

    # ── Internal: analysis ────────────────────────────────────────────────────

    def _analyze_and_store(
        self,
        db: Session,
        title: str,
        content: str,
        registry_id: int,
        strategy_id: int,
    ) -> None:
        """Run rule-based entity extraction + scoring, persist to article_analysis."""
        from app.models.article import ArticleAnalysis

        entities = self._extract_entities(title, content)
        relevance, sentiment, signal_strength, matched_topics = self._score_article(
            title, content
        )

        analysis = ArticleAnalysis(
            registry_id=registry_id,
            strategy_id=strategy_id,
            relevance_score=round(relevance, 2),
            sentiment_score=round(sentiment, 2),
            signal_strength=round(signal_strength, 2),
            entities_detected=json.dumps(entities),
            topics_detected=json.dumps(matched_topics),
            thesis_notes=self._build_thesis_notes(matched_topics),
        )
        db.add(analysis)
        logger.debug(
            "Analysis stored registry_id=%s relevance=%.2f signal=%.2f topics=%s",
            registry_id, relevance, signal_strength, matched_topics,
        )

    def _extract_entities(self, title: str, content: str) -> dict:
        """Lightweight rule-based entity extraction."""
        text = (title + " " + content).lower()

        countries = [c for c in _COUNTRIES if c in text]

        # Ticker extraction: $TICK or standalone uppercase 2-5 letter words
        raw_text = title + " " + content[:500]
        ticker_candidates: set[str] = set()
        for m in _TICKER_RE.finditer(raw_text):
            t = (m.group(1) or m.group(2) or "").upper()
            if t and t not in _NOT_TICKERS:
                ticker_candidates.add(t)

        return {
            "countries": sorted(countries),
            "tickers": sorted(ticker_candidates),
        }

    def _score_article(
        self, title: str, content: str
    ) -> tuple[float, float, float, list[str]]:
        """Return ``(relevance, sentiment, signal_strength, matched_rule_names)``.

        All scores are in the range ``[-1, 1]`` (relevance and signal_strength
        clamped to ``[0, 1]``).
        """
        if not self.pattern_rules:
            return 0.1, 0.0, 0.0, []

        text = (title + " " + content).lower()
        matched: list[dict] = []

        for rule in self.pattern_rules:
            keywords = rule.get("keywords", [])
            excludes = rule.get("exclude", [])

            has_keyword = any(kw.lower() in text for kw in keywords)
            has_exclude = any(ex.lower() in text for ex in excludes)

            if has_keyword and not has_exclude:
                matched.append(rule)

        if not matched:
            return 0.1, 0.0, 0.0, []

        confidences = [r["confidence"] for r in matched]
        relevance = min(1.0, sum(confidences) / len(confidences))
        signal_strength = max(confidences)

        _sentiment_map = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
        sentiments = [_sentiment_map.get(r.get("signal_type", "neutral"), 0.0) for r in matched]
        sentiment = sum(sentiments) / len(sentiments)

        matched_names = [r["name"] for r in matched]
        return relevance, sentiment, signal_strength, matched_names

    def _build_thesis_notes(self, matched_topics: list[str]) -> str | None:
        """Generate a one-line thesis note from matched rule names."""
        if not matched_topics:
            return None
        rules_by_name = {r["name"]: r for r in self.pattern_rules}
        notes = [
            rules_by_name[name]["description"]
            for name in matched_topics
            if name in rules_by_name
        ]
        return " | ".join(notes) if notes else None
