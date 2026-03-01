"""Three-tier article deduplication.

Layer 1 — URL match       (free, instant)
Layer 2 — Content hash    (cheap, fast)
Layer 3 — Fuzzy title     (difflib, last 24 h only)

Public API
----------
should_scrape(db, url, title, content_preview)
    → (True,  None,        None)          new article — scrape it
    → (False, registry_id, 'url_match')   URL seen before
    → (False, registry_id, 'content_match') same fingerprint, new URL
    → (False, registry_id, 'fuzzy_match') similar title within 24 h

register_alias(db, url, canonical_id, match_type)
    → None  (caller commits the session)
"""

from __future__ import annotations

import difflib
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.utils.url_normalizer import normalize_url

# ── Constants ─────────────────────────────────────────────────────────────────

FUZZY_THRESHOLD: float = 0.85
FUZZY_LOOKBACK_HOURS: int = 24

# ── Internal text helpers ─────────────────────────────────────────────────────

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


# ── Public pure functions ─────────────────────────────────────────────────────

def content_fingerprint(title: str, content_preview: str) -> str:
    """Return an MD5 hex digest of normalised title + first 500 chars of content.

    The fingerprint is designed to match the *same article* even when:
    - The URL changes (syndication, CDN rewrites)
    - Minor whitespace or punctuation differences exist between copies

    Args:
        title: Article headline (any length).
        content_preview: Raw article body — only the first 500 characters
            are used, so passing the full body is fine.

    Returns:
        32-character lowercase hex string (MD5).
    """
    normalised = (
        _normalize_text(title)
        + " "
        + _normalize_text(content_preview[:500])
    )
    return hashlib.md5(normalised.encode("utf-8")).hexdigest()


def fuzzy_title_similarity(title_a: str, title_b: str) -> float:
    """Return a 0–1 similarity score for two article titles.

    Uses ``difflib.SequenceMatcher`` on normalised (lowercase, no punct) text.
    Scores ≥ ``FUZZY_THRESHOLD`` (0.85) are treated as probable duplicates.
    """
    return difflib.SequenceMatcher(
        None,
        _normalize_text(title_a),
        _normalize_text(title_b),
    ).ratio()


# ── DB helpers ────────────────────────────────────────────────────────────────

def register_alias(
    db: Session,
    url: str,
    canonical_id: int,
    match_type: str,
) -> None:
    """Insert an ``article_url_aliases`` row for a duplicate URL.

    Does **not** commit — the caller owns the transaction.

    Args:
        db: Active SQLAlchemy session.
        url: The duplicate/alias URL (will be stored as-is, usually normalised).
        canonical_id: ``article_registry.id`` of the canonical record.
        match_type: One of ``'url_match'``, ``'content_match'``, ``'fuzzy_match'``.
    """
    from app.models.article import ArticleUrlAlias

    alias = ArticleUrlAlias(
        url=url,
        canonical_registry_id=canonical_id,
        match_type=match_type,
    )
    db.add(alias)


# ── Internal DB lookups ───────────────────────────────────────────────────────

def _touch(record, now: datetime) -> None:
    """Bump scrape_count and last_seen_at on a registry record."""
    record.scrape_count = (record.scrape_count or 0) + 1
    record.last_seen_at = now


# ── Main deduplication gate ───────────────────────────────────────────────────

def should_scrape(
    db: Session,
    url: str,
    title: str,
    content_preview: str,
) -> tuple[bool, int | None, str | None]:
    """Decide whether this article should be scraped and stored.

    Runs three increasingly expensive checks.  The first hit short-circuits
    the remaining layers.

    Args:
        db: Active SQLAlchemy session (read + write, caller commits).
        url: Raw URL as received from the feed.
        title: Article headline.
        content_preview: First N characters of body text (≥ 500 recommended).

    Returns:
        A 3-tuple ``(should_scrape, registry_id, match_type)``:

        * ``(True, None, None)``                       — new article
        * ``(False, id, 'url_match')``                 — URL already seen
        * ``(False, id, 'content_match')``             — body fingerprint match
        * ``(False, id, 'fuzzy_match')``               — similar title (24 h window)
    """
    from app.models.article import ArticleRegistry, ArticleUrlAlias

    now = datetime.now(timezone.utc)
    canonical_url = normalize_url(url)

    # ── Layer 1: URL match ────────────────────────────────────────────────────
    # Check the canonical registry table first.
    registry_hit = (
        db.query(ArticleRegistry)
        .filter(ArticleRegistry.url == canonical_url)
        .first()
    )
    if registry_hit:
        _touch(registry_hit, now)
        return False, registry_hit.id, "url_match"

    # Also check the aliases table (handles URLs we've seen as duplicates).
    alias_hit = (
        db.query(ArticleUrlAlias)
        .filter(ArticleUrlAlias.url == canonical_url)
        .first()
    )
    if alias_hit and alias_hit.canonical_registry_id:
        canonical = db.get(ArticleRegistry, alias_hit.canonical_registry_id)
        if canonical:
            _touch(canonical, now)
            return False, canonical.id, "url_match"

    # ── Layer 2: Content fingerprint ──────────────────────────────────────────
    c_hash = content_fingerprint(title, content_preview)
    hash_hit = (
        db.query(ArticleRegistry)
        .filter(ArticleRegistry.content_hash == c_hash)
        .first()
    )
    if hash_hit:
        register_alias(db, canonical_url, hash_hit.id, "content_match")
        _touch(hash_hit, now)
        return False, hash_hit.id, "content_match"

    # ── Layer 3: Fuzzy title match (last 24 h window) ─────────────────────────
    if title:
        cutoff = now - timedelta(hours=FUZZY_LOOKBACK_HOURS)
        recent = (
            db.query(ArticleRegistry)
            .filter(ArticleRegistry.last_seen_at >= cutoff)
            .filter(ArticleRegistry.title.isnot(None))
            .all()
        )
        for candidate in recent:
            if (
                candidate.title
                and fuzzy_title_similarity(title, candidate.title) >= FUZZY_THRESHOLD
            ):
                register_alias(db, canonical_url, candidate.id, "fuzzy_match")
                _touch(candidate, now)
                return False, candidate.id, "fuzzy_match"

    # ── New article ───────────────────────────────────────────────────────────
    return True, None, None
