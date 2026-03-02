"""Scraper configuration for the Propaganda Arbitrage strategy.

``CONFIG`` is the canonical source of truth.  ``get_scrapers()`` returns the
same sources in the format expected by ``RSSNewsScraper`` (backward-compatible
with ``tasks.py`` and ``article_processor.py``).

Source categories
-----------------
government_official  – White House, State Dept, USTR
western_mainstream   – Reuters, Bloomberg, FT, Foreign Policy, Economist
western_tech         – TechCrunch, Ars Technica
alternative_asia     – SCMP, Global Times
social_media         – Reddit WSB
"""

STRATEGY_NAME = "propaganda-arbitrage"

CONFIG: dict = {
    "name": STRATEGY_NAME,
    "sources": [
        # ── US Government / Official ──────────────────────────────────────────
        {
            "name": "White House News",
            "url": "https://www.whitehouse.gov/news/feed/",
            "type": "rss",
            "bias": "government",
            "category": "government_official",
            "tags": ["government", "policy", "executive"],
            "priority": 1,
        },
        {
            "name": "State Department Press Releases",
            "url": "https://www.state.gov/rss-feeds/press-releases/",
            "type": "rss",
            "bias": "government",
            "category": "government_official",
            "tags": ["government", "foreign-policy", "sanctions"],
            "priority": 1,
        },
        {
            "name": "USTR News",
            "url": "https://ustr.gov/rss.xml",
            "type": "rss",
            "bias": "government",
            "category": "government_official",
            "tags": ["trade", "tariffs", "policy"],
            "priority": 1,
        },
        # ── Western Mainstream ────────────────────────────────────────────────
        {
            "name": "Reuters Business",
            "url": "https://news.google.com/rss/search?q=when:24h+allinurl:reuters.com+business&ceid=US:en&hl=en-US&gl=US",
            "type": "rss",
            "bias": "center",
            "category": "western_mainstream",
            "tags": ["finance", "markets", "global"],
            "priority": 2,
        },
        {
            "name": "Reuters Tech",
            "url": "https://news.google.com/rss/search?q=when:24h+allinurl:reuters.com+technology&ceid=US:en&hl=en-US&gl=US",
            "type": "rss",
            "bias": "center",
            "category": "western_mainstream",
            "tags": ["technology", "semiconductor", "ai"],
            "priority": 2,
        },
        {
            "name": "Financial Times",
            "url": "https://www.ft.com/rss/home",
            "type": "rss",
            "bias": "center",
            "category": "western_mainstream",
            "tags": ["finance", "markets", "global"],
            "priority": 2,
        },
        {
            "name": "Bloomberg Markets",
            "url": "https://feeds.bloomberg.com/markets/news.rss",
            "type": "rss",
            "bias": "center",
            "category": "western_mainstream",
            "tags": ["finance", "markets"],
            "priority": 2,
        },
        {
            "name": "Foreign Policy",
            "url": "https://foreignpolicy.com/feed/",
            "type": "rss",
            "bias": "center",
            "category": "western_mainstream",
            "tags": ["geopolitics", "diplomacy"],
            "priority": 2,
        },
        {
            "name": "The Economist – World",
            "url": "https://www.economist.com/the-world-this-week/rss.xml",
            "type": "rss",
            "bias": "center",
            "category": "western_mainstream",
            "tags": ["geopolitics", "economics"],
            "priority": 3,
        },
        # ── Western Tech ──────────────────────────────────────────────────────
        {
            "name": "TechCrunch",
            "url": "https://techcrunch.com/feed/",
            "type": "rss",
            "bias": "center-left",
            "category": "western_tech",
            "tags": ["technology", "startups", "ai"],
            "priority": 3,
        },
        {
            "name": "Ars Technica",
            "url": "https://arstechnica.com/feed/",
            "type": "rss",
            "bias": "center-left",
            "category": "western_tech",
            "tags": ["technology", "semiconductor", "science"],
            "priority": 3,
        },
        # ── Alternative / Asia ────────────────────────────────────────────────
        {
            "name": "South China Morning Post",
            "url": "https://www.scmp.com/rss/91/feed",
            "type": "rss",
            "bias": "center",
            "category": "alternative_asia",
            "tags": ["china", "asia", "geopolitics", "technology"],
            "priority": 2,
        },
        {
            "name": "Global Times",
            "url": "https://www.globaltimes.cn/rss/outbrain.xml",
            "type": "rss",
            "bias": "left",
            "category": "alternative_asia",
            "tags": ["china", "geopolitics", "policy"],
            "priority": 2,
        },
        # ── Social Sentiment ──────────────────────────────────────────────────
        {
            "name": "Reddit WallStreetBets (RSS)",
            "url": "https://www.reddit.com/r/wallstreetbets/top.rss?t=day",
            "type": "rss",
            "bias": "social",
            "category": "social_media",
            "tags": ["retail-sentiment", "social"],
            "priority": 4,
        },
        {
            "name": "Reddit Investing",
            "url": "https://www.reddit.com/r/investing/top.rss?t=day",
            "type": "rss",
            "bias": "social",
            "category": "social_media",
            "tags": ["retail-sentiment", "investing", "markets"],
            "priority": 4,
        },
        {
            "name": "Reddit Geopolitics",
            "url": "https://www.reddit.com/r/geopolitics/top.rss?t=day",
            "type": "rss",
            "bias": "social",
            "category": "social_media",
            "tags": ["geopolitics", "social"],
            "priority": 4,
        },
        {
            "name": "Reddit World News",
            "url": "https://www.reddit.com/r/worldnews/top.rss?t=day",
            "type": "rss",
            "bias": "social",
            "category": "social_media",
            "tags": ["global", "news", "social"],
            "priority": 4,
        },
        # ── Curated ───────────────────────────────────────────────────────────
        {
            "name": "Flipboard – MyNews",
            "url": "https://flipboard.com/@alexrmanescu/mynews-jdtlldphy.rss",
            "type": "rss",
            "bias": "curated",
            "category": "western_mainstream",
            "tags": ["curated", "finance", "geopolitics", "ai"],
            "priority": 2,
        },
        # ── Trends ────────────────────────────────────────────────────────────
        {
            "name": "Google Trends US",
            "url": "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US",
            "type": "rss",
            "bias": "neutral",
            "category": "social_media",
            "tags": ["trends", "sentiment", "retail"],
            "priority": 4,
        },
    ],
    "update_interval_minutes": 60,
    "min_gap_threshold": 5,
}


def get_scrapers() -> list[dict]:
    """Return RSS sources in the format expected by ``RSSNewsScraper``.

    Each dict has: ``name``, ``url``, ``type``, ``bias``, ``category``,
    ``tags``, ``priority``.  The scraping pipeline uses ``url`` and ``type``;
    ``bias`` and ``category`` are consumed by ``PatternDetector``.
    """
    return CONFIG["sources"]
