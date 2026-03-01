"""PAE command-line interface.

Usage examples::

    # Dry-run scrape (no DB writes, shows first 5 articles)
    python -m app.cli scrape --strategy propaganda-arbitrage --test

    # Live scrape with limit
    python -m app.cli scrape --strategy propaganda-arbitrage --limit 20

    # Check DB connectivity
    python -m app.cli db-ping
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import pathlib
import sys
import textwrap

logger = logging.getLogger(__name__)


# ── Strategy loader (same pattern as tasks.py) ────────────────────────────────

def _load_strategy(name: str):
    """Load scraper_config and pattern_rules from a strategy directory."""
    root = pathlib.Path(__file__).parent.parent / "strategies" / name

    def _load_module(filename: str, module_name: str):
        path = root / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing: {path}")
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    scraper_mod = _load_module("scraper_config.py", f"_cli_{name}_scraper")
    rules_mod = _load_module("pattern_rules.py", f"_cli_{name}_rules")
    return scraper_mod, rules_mod


# ── Sub-commands ──────────────────────────────────────────────────────────────

def cmd_db_ping(_args: argparse.Namespace) -> int:
    """Check database connectivity and print status."""
    from app.core.database import ping_db
    from app.core.config import settings

    if ping_db():
        print(f"[OK] Database reachable: {settings.database_url}")
        return 0
    else:
        print(f"[FAIL] Cannot reach database: {settings.database_url}", file=sys.stderr)
        return 1


def cmd_scrape(args: argparse.Namespace) -> int:
    """Scrape articles for a strategy, with optional dry-run display."""
    strategy_name: str = args.strategy
    limit: int = args.limit
    test_mode: bool = args.test

    print(f"\nPAE Scraper — strategy: {strategy_name}")
    print("=" * 60)

    # ── Load strategy ─────────────────────────────────────────────────────────
    try:
        scraper_mod, rules_mod = _load_strategy(strategy_name)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    scrapers = scraper_mod.get_scrapers()
    pattern_rules = getattr(rules_mod, "PATTERN_RULES", [])
    print(f"Loaded {len(scrapers)} scraper sources, {len(pattern_rules)} pattern rules")

    # ── Fetch articles ────────────────────────────────────────────────────────
    from app.services.scrapers.rss_scraper import RSSNewsScraper, ScraperError

    rss = RSSNewsScraper()
    feed_urls = [s["url"] for s in scrapers if s.get("type", "rss") == "rss"]
    effective_limit = limit if not test_mode else min(limit, 5)

    print(f"\nFetching from {len(feed_urls)} feeds (limit={effective_limit})…")
    articles: list[dict] = []

    for scraper_cfg in scrapers[:effective_limit] if test_mode else scrapers:
        feed_url = scraper_cfg.get("url", "")
        if not feed_url or scraper_cfg.get("type", "rss") != "rss":
            continue
        try:
            feed_articles = rss.scrape_feed(feed_url)
            articles.extend(feed_articles[:effective_limit - len(articles)])
            if len(articles) >= effective_limit:
                break
        except ScraperError as exc:
            print(f"  [WARN] {scraper_cfg.get('name', feed_url)}: {exc}")

    print(f"Fetched {len(articles)} articles\n")

    # ── Test mode: display and exit ───────────────────────────────────────────
    if test_mode:
        _display_articles(articles, pattern_rules)
        return 0

    # ── Live mode: process through pipeline ───────────────────────────────────
    from app.core.database import db_session, init_db, ping_db
    from app.models import Strategy
    from app.services.scrapers.article_processor import ArticleProcessor

    if not ping_db():
        print("[ERROR] Database unreachable — aborting", file=sys.stderr)
        return 1

    init_db()
    processor = ArticleProcessor(strategy_name, pattern_rules)
    counts = {k: 0 for k in ("scraped_new", "analyzed_existing", "skipped", "error")}

    with db_session() as db:
        # Ensure strategy row exists
        strategy_row = db.query(Strategy).filter(Strategy.name == strategy_name).first()
        if not strategy_row:
            from app.models import Strategy as S
            strategy_row = S(name=strategy_name, is_active=True)
            db.add(strategy_row)
            db.flush()

        for article in articles:
            try:
                status, rid = processor.process_article(
                    db=db,
                    url=article["url"],
                    title=article["title"],
                    content=article["content"],
                    strategy_id=strategy_row.id,
                    published_at=article.get("published_at"),
                )
                counts[status] += 1
            except Exception as exc:
                logger.exception("Error processing article %s", article.get("url"))
                counts["error"] += 1

    print("\nResults:")
    for k, v in counts.items():
        print(f"  {k:<22}: {v}")
    return 0


def _display_articles(articles: list[dict], pattern_rules: list[dict]) -> None:
    """Pretty-print articles with dedup simulation and pattern matching."""
    from app.utils.dedup import content_fingerprint, fuzzy_title_similarity

    print(f"{'─' * 60}")
    seen_hashes: set[str] = set()
    seen_titles: list[str] = []

    for i, article in enumerate(articles, 1):
        title = article.get("title", "(no title)")
        url = article.get("url", "")
        feed = article.get("feed_name", "")
        pub = article.get("published_at")
        pub_str = pub.strftime("%Y-%m-%d %H:%M UTC") if pub else "unknown"
        content = article.get("content", "")

        # Simulate dedup
        c_hash = content_fingerprint(title, content[:500])
        dedup_flag = ""
        if c_hash in seen_hashes:
            dedup_flag = "  [DEDUP: content_match]"
        else:
            for prev_title in seen_titles:
                if fuzzy_title_similarity(title, prev_title) >= 0.85:
                    dedup_flag = "  [DEDUP: fuzzy_match]"
                    break

        seen_hashes.add(c_hash)
        seen_titles.append(title)

        # Pattern matching
        text = (title + " " + content).lower()
        matched_rules = [
            r["name"] for r in pattern_rules
            if any(kw.lower() in text for kw in r.get("keywords", []))
            and not any(ex.lower() in text for ex in r.get("exclude", []))
        ]

        print(f"\n[{i}] {title}{dedup_flag}")
        print(f"     Feed    : {feed}")
        print(f"     URL     : {url[:80]}{'…' if len(url) > 80 else ''}")
        print(f"     Published: {pub_str}")
        if matched_rules:
            print(f"     Rules   : {', '.join(matched_rules)}")
        if content:
            preview = textwrap.shorten(content, width=120, placeholder="…")
            print(f"     Preview : {preview}")

    print(f"\n{'─' * 60}")
    print(f"Test mode: {len(articles)} articles shown. No data written to DB.")


# ── Entry point ───────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="PAE — Propaganda Arbitrage Engine CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scrape
    p_scrape = sub.add_parser("scrape", help="Scrape articles for a strategy")
    p_scrape.add_argument(
        "--strategy", required=True,
        help="Strategy directory name (e.g. propaganda-arbitrage)",
    )
    p_scrape.add_argument(
        "--test", action="store_true",
        help="Dry-run: fetch up to 5 articles and display results without writing to DB",
    )
    p_scrape.add_argument(
        "--limit", type=int, default=50,
        help="Maximum number of articles to process (default: 50)",
    )

    # db-ping
    sub.add_parser("db-ping", help="Test database connectivity")

    return parser


def main() -> None:
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "scrape": cmd_scrape,
        "db-ping": cmd_db_ping,
    }
    handler = handlers.get(args.command)
    if handler:
        sys.exit(handler(args))


if __name__ == "__main__":
    main()
