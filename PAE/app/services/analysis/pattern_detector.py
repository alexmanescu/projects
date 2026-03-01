"""Coverage-gap and policy-signal detection for the PAE pipeline.

``PatternDetector`` is strategy-agnostic: it accepts the numeric thresholds
from a strategy's ``PATTERNS`` dict and applies them to any article list.

Article dicts are expected to carry a ``category`` field (one of
``government_official``, ``western_mainstream``, ``western_tech``,
``alternative_asia``, ``social_media``) populated by the scraping layer when
the feed config is known.  Articles without ``category`` default to
``"unknown"`` and are excluded from bias-sensitive counts.
"""

from __future__ import annotations

import re
from collections import defaultdict

# ── Entity vocabularies ───────────────────────────────────────────────────────

# Case-sensitive (exact word-boundary match)
_COMPANIES: frozenset[str] = frozenset(
    {
        "TSMC", "SMIC", "Intel", "NVIDIA", "AMD", "Samsung", "Huawei",
        "ASML", "Qualcomm", "Micron", "Apple", "Microsoft", "Google",
        "Tesla", "Meta", "Amazon", "SK Hynix", "Broadcom", "MediaTek",
        "Foxconn", "CATL", "BYD",
    }
)

# Case-insensitive (lower-case comparison)
_COUNTRIES: frozenset[str] = frozenset(
    {
        "china", "taiwan", "us", "usa", "united states", "japan",
        "korea", "south korea", "north korea", "eu", "europe",
        "russia", "india", "germany", "france", "uk", "britain",
    }
)

# Case-insensitive topic keywords
_TOPICS: frozenset[str] = frozenset(
    {
        "semiconductor", "chip", "ai", "artificial intelligence",
        "lithium", "battery", "5g", "quantum", "solar", "ev",
        "electric vehicle", "drone", "satellite", "nuclear",
        "rare earth", "supply chain",
    }
)

# ── Monetary amount extraction ────────────────────────────────────────────────

# Matches: "$5 billion", "USD 3.2 trillion", "50 million dollars", "¥200 billion"
_MONEY_RE = re.compile(
    r"""
    (?:                         # optional currency symbol
        [\$£€¥]
        |USD\s*|CNY\s*|EUR\s*
    )?
    ([\d,]+(?:\.\d+)?)          # numeric part
    \s*
    (trillion|billion|million)  # magnitude word
    (?:\s*dollars?)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_MAGNITUDE: dict[str, float] = {
    "trillion": 1e12,
    "billion": 1e9,
    "million": 1e6,
}

# ── Source category groupings for gap analysis ────────────────────────────────

_WESTERN_CATEGORIES: frozenset[str] = frozenset(
    {"western_mainstream", "western_tech", "government_official"}
)
_ASIA_CATEGORIES: frozenset[str] = frozenset({"alternative_asia"})

# ── Policy keywords ───────────────────────────────────────────────────────────

_POLICY_KEYWORDS: frozenset[str] = frozenset(
    {
        "subsidy", "subsidies", "fund", "funding", "billion", "trillion",
        "investment", "policy", "regulation", "legislation", "executive order",
        "act", "directive", "mandate", "ban", "restriction",
    }
)


class PatternDetector:
    """Detect coverage gaps and policy signals in a batch of articles.

    Args:
        pattern_config: ``PATTERNS`` dict from a strategy's ``pattern_rules.py``.
            If omitted, default thresholds are used.
    """

    _DEFAULT_CONFIG: dict = {
        "coverage_gap": {
            "min_asia_articles": 5,
            "max_western_articles": 2,
            "min_gap_ratio": 3.0,
        },
        "policy_catalyst": {
            "keywords": list(_POLICY_KEYWORDS),
            "min_amount": 1_000_000_000,
        },
        "entities_of_interest": [],
    }

    def __init__(self, pattern_config: dict | None = None) -> None:
        cfg = pattern_config or {}
        self._gap_cfg: dict = {**self._DEFAULT_CONFIG["coverage_gap"],
                               **cfg.get("coverage_gap", {})}
        self._policy_cfg: dict = {**self._DEFAULT_CONFIG["policy_catalyst"],
                                  **cfg.get("policy_catalyst", {})}
        self._entities_of_interest: list[str] = (
            cfg.get("entities_of_interest", [])
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze_coverage_gaps(
        self, articles: list[dict], strategy_id: int
    ) -> list[dict]:
        """Identify topics that are over-covered in Asian sources vs Western.

        Algorithm:
        1. Extract entities from each article's title + summary.
        2. Group articles by the first detected entity (or ``"general"``).
        3. Count ``western_count`` and ``asia_count`` per entity group.
        4. Flag groups where:
           - ``asia_count >= min_asia_articles``  (default 5)
           - ``western_count <= max_western_articles`` (default 2)
           - ``gap_ratio >= min_gap_ratio``  (default 3.0)
        5. Return flagged groups sorted by ``gap_ratio`` descending.

        Args:
            articles: List of article dicts, each with ``title``, ``summary``
                (or ``content``), and optionally ``category``.
            strategy_id: Included in each returned gap dict for traceability.

        Returns:
            List of gap dicts::

                {
                  "topic": str,
                  "western_count": int,
                  "asia_count": int,
                  "gap_ratio": float,
                  "article_titles": list[str],
                  "strategy_id": int,
                }
        """
        # Build entity → {category: [article, ...]} index
        entity_buckets: dict[str, dict[str, list[dict]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for article in articles:
            text = article.get("title", "") + " " + (
                article.get("summary", "") or article.get("content", "")[:300]
            )
            entities = self.extract_entities(text)
            # Assign to the first matched entity; fall back to "general"
            topic = entities[0] if entities else "general"
            category = article.get("category", "unknown")
            entity_buckets[topic][category].append(article)

        gaps: list[dict] = []
        min_asia = self._gap_cfg["min_asia_articles"]
        max_western = self._gap_cfg["max_western_articles"]
        min_ratio = self._gap_cfg["min_gap_ratio"]

        for topic, cat_map in entity_buckets.items():
            western_count = sum(
                len(v) for k, v in cat_map.items() if k in _WESTERN_CATEGORIES
            )
            asia_count = sum(
                len(v) for k, v in cat_map.items() if k in _ASIA_CATEGORIES
            )

            if asia_count < min_asia or western_count > max_western:
                continue

            gap_ratio = asia_count / max(western_count, 1)
            if gap_ratio < min_ratio:
                continue

            all_articles = [a for arts in cat_map.values() for a in arts]
            titles = [a.get("title", "") for a in all_articles if a.get("title")]

            gaps.append(
                {
                    "topic": topic,
                    "western_count": western_count,
                    "asia_count": asia_count,
                    "gap_ratio": round(gap_ratio, 2),
                    "article_titles": titles[:20],
                    "strategy_id": strategy_id,
                }
            )

        gaps.sort(key=lambda g: g["gap_ratio"], reverse=True)
        return gaps

    def detect_policy_announcements(self, articles: list[dict]) -> list[dict]:
        """Find articles that reference government policy, funding, or regulation.

        Detection criteria:
        - Contains at least one policy keyword.
        - Optionally contains a monetary amount ≥ ``min_amount``.

        Args:
            articles: List of article dicts with ``title`` and ``content``
                (or ``summary``).

        Returns:
            Filtered list of articles, each extended with::

                {
                  "policy_keywords_matched": list[str],
                  "amounts_detected": list[float],   # in USD
                  "max_amount": float | None,
                }
        """
        policy_keywords = [k.lower() for k in self._policy_cfg.get("keywords", [])]
        min_amount = self._policy_cfg.get("min_amount", 0)
        results: list[dict] = []

        for article in articles:
            text = (
                (article.get("title", "") or "")
                + " "
                + (article.get("content", "") or article.get("summary", "") or "")
            ).lower()

            matched_kws = [kw for kw in policy_keywords if kw in text]
            if not matched_kws:
                continue

            amounts = self._extract_amounts(text)
            significant = [a for a in amounts if a >= min_amount]

            result = {
                **article,
                "policy_keywords_matched": matched_kws,
                "amounts_detected": significant,
                "max_amount": max(significant) if significant else None,
            }
            results.append(result)

        return results

    def extract_entities(self, text: str) -> list[str]:
        """Extract known entities from free text using keyword matching.

        Detects:
        - **Companies** (case-sensitive): TSMC, NVIDIA, Samsung, …
        - **Countries** (case-insensitive): China, Taiwan, US, …
        - **Topics** (case-insensitive): semiconductor, chip, AI, …
        - **Entities of interest** from the strategy config (case-insensitive
          for multi-word entries, exact-word for single tokens).

        Args:
            text: Any free-form text (title + body is typical).

        Returns:
            Deduplicated list of matched entity strings, preserving insertion
            order (companies first, then countries, then topics).
        """
        found: list[str] = []
        seen: set[str] = set()

        def _add(entity: str) -> None:
            if entity not in seen:
                seen.add(entity)
                found.append(entity)

        # Companies: exact word-boundary, case-sensitive
        for company in _COMPANIES:
            if re.search(rf"\b{re.escape(company)}\b", text):
                _add(company)

        # Countries: case-insensitive
        text_lower = text.lower()
        for country in _COUNTRIES:
            if re.search(rf"\b{re.escape(country)}\b", text_lower):
                _add(country.title() if len(country) > 2 else country.upper())

        # Topics: case-insensitive substring match
        for topic in _TOPICS:
            if topic in text_lower:
                _add(topic)

        # Strategy-specific entities of interest
        for entity in self._entities_of_interest:
            pattern = rf"\b{re.escape(entity)}\b"
            if re.search(pattern, text, re.IGNORECASE):
                if entity not in seen:
                    _add(entity)

        return found

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_amounts(text: str) -> list[float]:
        """Return all monetary amounts (in USD equivalent) found in *text*."""
        amounts: list[float] = []
        for m in _MONEY_RE.finditer(text):
            try:
                numeric = float(m.group(1).replace(",", ""))
                magnitude = _MAGNITUDE[m.group(2).lower()]
                amounts.append(numeric * magnitude)
            except (ValueError, KeyError):
                continue
        return amounts
