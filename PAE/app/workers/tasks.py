"""Main worker loop for PAE strategies.

Usage::

    python -m app.workers.tasks <strategy-name>

Example::

    python -m app.workers.tasks propaganda-arbitrage

Scheduled task functions (called by ``app.workers.scheduler``)::

    scrape_all_strategies()   — full pipeline for every active strategy
    monitor_positions()       — exit-signal detection on open positions
    detect_confluence()       — cross-strategy signal aggregation
    check_stop_losses()       — proximity alerts for stop-loss levels
    update_position_prices()  — refresh current prices in the DB
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from types import ModuleType

from app.core.config import settings
from app.core.database import db_session, init_db, ping_db

logger = logging.getLogger(__name__)


# ── Strategy interface ────────────────────────────────────────────────────────

def _load_strategy_module(name: str) -> ModuleType:
    """Load ``strategies/<name>/scraper_config.py`` from its file path.

    Strategy directories may contain hyphens (e.g. ``propaganda-arbitrage``),
    which are illegal in Python dotted import paths, so we use
    ``importlib.util.spec_from_file_location`` instead of ``import_module``.

    The module must expose:
    - ``get_scrapers() -> list[dict]``  — scraper configurations
    - ``STRATEGY_NAME: str``            — canonical name matching DB record
    """
    import importlib.util
    import pathlib

    strategies_root = pathlib.Path(__file__).parent.parent.parent / "strategies"
    module_file = strategies_root / name / "scraper_config.py"

    if not module_file.exists():
        raise FileNotFoundError(
            f"Strategy module not found: {module_file}\n"
            f"Expected: strategies/{name}/scraper_config.py"
        )

    spec = importlib.util.spec_from_file_location(f"_pae_strategy_{name}_scraper", module_file)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.error("Failed to load strategy module %s: %s", module_file, exc)
        raise
    return module


# ── Core pipeline ─────────────────────────────────────────────────────────────

def run_scrape_cycle(strategy_name: str) -> dict:
    """Execute one full scrape → analyse → signal cycle for *strategy_name*.

    Returns:
        Dict with keys ``scraped_new``, ``analyzed_existing``, ``skipped``,
        ``error``.
    """
    from app.models import Strategy
    from app.services.scrapers.rss_scraper import RSSNewsScraper, ScraperError
    from app.services.scrapers.article_processor import ArticleProcessor

    logger.info("Starting scrape cycle for strategy: %s", strategy_name)

    module = _load_strategy_module(strategy_name)
    scrapers = module.get_scrapers()
    pattern_rules = getattr(module, "PATTERN_RULES", [])

    # Load pattern_rules from the companion module if not on the scraper module
    if not pattern_rules:
        import importlib.util, pathlib
        rules_path = (
            pathlib.Path(__file__).parent.parent.parent
            / "strategies" / strategy_name / "pattern_rules.py"
        )
        if rules_path.exists():
            spec = importlib.util.spec_from_file_location("_rules", rules_path)
            rules_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rules_mod)
            pattern_rules = getattr(rules_mod, "PATTERN_RULES", [])

    rss = RSSNewsScraper()
    processor = ArticleProcessor(strategy_name, pattern_rules)
    counts = {"scraped_new": 0, "analyzed_existing": 0, "skipped": 0, "error": 0}

    with db_session() as session:
        # Ensure strategy row exists
        strategy_row = (
            session.query(Strategy).filter(Strategy.name == strategy_name).first()
        )
        if not strategy_row:
            strategy_row = Strategy(name=strategy_name, is_active=True)
            session.add(strategy_row)
            session.flush()

        for scraper_cfg in scrapers:
            source_name = scraper_cfg.get("name", "unknown")
            feed_url = scraper_cfg.get("url", "")
            if not feed_url or scraper_cfg.get("type", "rss") != "rss":
                continue

            try:
                articles = rss.scrape_feed(feed_url)
            except ScraperError:
                logger.error("Skipping source %s after fetch failure", source_name)
                continue

            if settings.dry_run:
                logger.info("[DRY RUN] %s: would process %d articles", source_name, len(articles))
                continue

            for article in articles:
                try:
                    status, _ = processor.process_article(
                        db=session,
                        url=article["url"],
                        title=article["title"],
                        content=article["content"],
                        strategy_id=strategy_row.id,
                        published_at=article.get("published_at"),
                    )
                    counts[status] += 1
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Error processing article %s", article.get("url")
                    )
                    counts["error"] += 1

    logger.info(
        "Scrape cycle complete for %s: %s",
        strategy_name,
        " | ".join(f"{k}={v}" for k, v in counts.items()),
    )
    return counts


# ── Scheduled tasks ───────────────────────────────────────────────────────────

def scrape_all_strategies() -> dict:
    """Run the full scrape → detect → alert pipeline for every active strategy.

    Loads all ``is_active=True`` strategies from the DB via
    :class:`~app.core.strategy_loader.StrategyLoader`, then calls
    :func:`_run_strategy_pipeline` for each one.  A failure in one strategy
    is logged but does not block the others.

    Returns:
        Dict mapping strategy name → per-strategy article counts dict.
    """
    from app.core.strategy_loader import StrategyLoader

    logger.info("scrape_all_strategies: loading active strategies")
    with db_session() as db:
        loader = StrategyLoader()
        strategies = loader.get_active_strategies(db)

    if not strategies:
        logger.warning("scrape_all_strategies: no active strategies found")
        return {}

    results: dict = {}
    for cfg in strategies:
        name = cfg["name"]
        logger.info("scrape_all_strategies: starting pipeline for %r", name)
        try:
            counts = _run_strategy_pipeline(cfg)
            results[name] = counts
        except Exception:
            logger.exception("scrape_all_strategies: pipeline failed for %r", name)
            results[name] = {"error": "pipeline exception"}

    logger.info(
        "scrape_all_strategies: complete — %d strategies processed",
        len(results),
    )
    return results


def _run_strategy_pipeline(cfg: dict) -> dict:
    """Scrape, process, pattern-detect, and alert for a single strategy config.

    Steps:
    1. Scrape RSS sources; annotate each article with its ``category`` from the
       source config (so PatternDetector can do coverage-gap analysis).
    2. Process each article through the dedup + article-processor pipeline.
    3. Run PatternDetector on the in-memory article list.
    4. For each coverage gap above threshold, generate an LLM thesis, write a
       Signal row, and send a Telegram opportunity alert.

    Args:
        cfg: Combined strategy config dict returned by
            :meth:`~app.core.strategy_loader.StrategyLoader.load_strategy`.

    Returns:
        Dict with keys: ``scraped_new``, ``analyzed_existing``, ``skipped``,
        ``error``, ``gaps_detected``, ``opportunities_sent``.
    """
    from app.models import Strategy, Signal
    from app.services.scrapers.rss_scraper import RSSNewsScraper, ScraperError
    from app.services.scrapers.article_processor import ArticleProcessor
    from app.services.analysis.pattern_detector import PatternDetector
    from app.services.analysis.llm_synthesizer import LLMSynthesizer
    from app.services.notifications.telegram_notifier import TelegramNotifier

    strategy_name = cfg["name"]
    strategy_id: int | None = cfg.get("db_id")
    pattern_rules = cfg.get("pattern_rules", [])
    patterns = cfg.get("patterns", {})
    sources = cfg.get("sources", [])

    rss = RSSNewsScraper()
    processor = ArticleProcessor(strategy_name, pattern_rules)
    counts: dict = {
        "scraped_new": 0, "analyzed_existing": 0,
        "skipped": 0, "error": 0,
        "gaps_detected": 0, "opportunities_sent": 0,
    }

    # ── Scrape + process ──────────────────────────────────────────────────────
    # Collect articles with categories for in-memory pattern detection.
    all_articles: list[dict] = []

    with db_session() as db:
        for source in sources:
            feed_url = source.get("url", "")
            category = source.get("category", "unknown")
            if not feed_url or source.get("type", "rss") != "rss":
                continue

            try:
                articles = rss.scrape_feed(feed_url)
            except ScraperError:
                logger.error("_run_strategy_pipeline: skipping %s after fetch failure",
                             source.get("name", feed_url))
                continue

            for article in articles:
                # Tag with source category so PatternDetector can bucket it.
                tagged = {**article, "category": category}
                all_articles.append(tagged)

                if settings.dry_run:
                    continue

                try:
                    status, _ = processor.process_article(
                        db=db,
                        url=article["url"],
                        title=article["title"],
                        content=article["content"],
                        strategy_id=strategy_id,
                        published_at=article.get("published_at"),
                    )
                    counts[status] += 1
                except Exception:
                    logger.exception("_run_strategy_pipeline: error processing %s",
                                     article.get("url"))
                    counts["error"] += 1

    if settings.dry_run:
        logger.info(
            "[DRY_RUN] %s: would process %d articles across %d sources",
            strategy_name, len(all_articles), len(sources),
        )
        return counts

    # ── Pattern detection ─────────────────────────────────────────────────────
    if not patterns or not all_articles:
        return counts

    detector = PatternDetector(patterns)
    gaps = detector.analyze_coverage_gaps(all_articles, strategy_id or 0)
    counts["gaps_detected"] = len(gaps)

    if not gaps:
        logger.debug("_run_strategy_pipeline: no coverage gaps for %s", strategy_name)
        return counts

    logger.info("_run_strategy_pipeline: %d gap(s) detected for %s", len(gaps), strategy_name)

    # ── LLM thesis + Signal write + alert ─────────────────────────────────────
    llm = LLMSynthesizer(
        ollama_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        claude_key=settings.anthropic_api_key,
        claude_model=settings.claude_model,
    )
    notifier = TelegramNotifier()

    for gap in gaps[:3]:   # cap at 3 alerts per strategy per cycle
        entity = gap.get("entity", "")
        if not entity:
            continue

        gap_ratio = float(gap.get("gap_ratio", 1.0))
        confidence = min(gap_ratio / 10.0, 1.0)

        # Write Signal row so detect_confluence() can aggregate across strategies
        _write_signal(
            strategy_id=strategy_id,
            ticker=entity,
            signal_type="coverage_gap",
            confidence=confidence,
            raw=gap,
        )

        # Generate LLM thesis
        try:
            thesis = llm.generate_thesis(gap, strategy_id or 0)
        except Exception as exc:
            logger.warning("Thesis generation failed for %s: %s", entity, exc)
            thesis = (
                f"Coverage gap detected: {entity} has {gap.get('asia_count', 0)} "
                f"Asian vs {gap.get('western_count', 0)} Western articles "
                f"(gap ratio: {gap_ratio:.1f}x)."
            )

        opportunity = {
            "ticker": entity,
            "topic": "coverage_gap",
            "thesis": thesis,
            "western_count": gap.get("western_count", 0),
            "asia_count": gap.get("asia_count", 0),
            "gap_ratio": gap_ratio,
            "amount": 10_000.0,
            "stop_loss_pct": 5.0,
            "strategy_id": strategy_id,
            "confluence_score": confidence,
        }

        try:
            asyncio.run(notifier.send_opportunity_alert(opportunity))
            counts["opportunities_sent"] += 1
        except RuntimeError:
            # Already inside an event loop — use nest_asyncio or run in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(asyncio.run, notifier.send_opportunity_alert(opportunity))
                fut.result(timeout=30)
            counts["opportunities_sent"] += 1
        except Exception as exc:
            logger.error("Failed to send opportunity alert for %s: %s", entity, exc)

    return counts


def run_detection_cycle(strategy_name: str) -> dict:
    """Pattern detection and signal generation worker (GPU machine).

    Designed to run on a second machine (e.g. Windows GPU host) that shares
    the same MySQL database as the scrape worker running on the Mac Mini.

    Steps:
    1. Scrape RSS feeds to rebuild a category-tagged article list — fast
       (~seconds, no LLM).  Article processing is **skipped**; the Mac Mini
       worker already handled that via :func:`run_scrape_cycle`.
    2. Run :class:`PatternDetector` on the article list.
    3. For each coverage gap: generate an LLM trade thesis (GPU Ollama),
       write a :class:`Signal` row, and send a Telegram opportunity alert.

    Returns:
        Dict with keys: ``articles_fetched``, ``gaps_detected``,
        ``opportunities_sent``, ``error``.
    """
    from app.models import Strategy
    from app.services.scrapers.rss_scraper import RSSNewsScraper, ScraperError
    from app.services.analysis.pattern_detector import PatternDetector
    from app.services.analysis.llm_synthesizer import LLMSynthesizer
    from app.services.notifications.telegram_notifier import TelegramNotifier

    logger.info("Starting detection cycle for strategy: %s", strategy_name)

    module = _load_strategy_module(strategy_name)
    sources = module.get_scrapers()

    # Load PATTERNS (coverage-gap thresholds) from pattern_rules.py
    patterns: dict = {}
    import importlib.util, pathlib
    rules_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "strategies" / strategy_name / "pattern_rules.py"
    )
    if rules_path.exists():
        spec = importlib.util.spec_from_file_location("_rules", rules_path)
        rules_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rules_mod)
        patterns = getattr(rules_mod, "PATTERNS", {})

    # ── Scrape for category-tagged article list (no LLM) ──────────────────────
    rss = RSSNewsScraper()
    all_articles: list[dict] = []
    counts: dict = {"articles_fetched": 0, "gaps_detected": 0, "opportunities_sent": 0, "error": 0}

    for source in sources:
        feed_url = source.get("url", "")
        category = source.get("category", "unknown")
        if not feed_url or source.get("type", "rss") != "rss":
            continue
        try:
            articles = rss.scrape_feed(feed_url)
        except ScraperError:
            logger.warning("detection_cycle: skipping %s after fetch failure",
                           source.get("name", feed_url))
            counts["error"] += 1
            continue
        for article in articles:
            all_articles.append({**article, "category": category})

    counts["articles_fetched"] = len(all_articles)
    logger.info("detection_cycle: %d articles fetched across %d sources",
                len(all_articles), len(sources))

    if not all_articles or not patterns:
        logger.info("detection_cycle: nothing to detect — exiting early")
        return counts

    # ── Look up strategy DB id ─────────────────────────────────────────────────
    strategy_id: int | None = None
    with db_session() as db:
        row = db.query(Strategy).filter(Strategy.name == strategy_name).first()
        if row:
            strategy_id = row.id

    # ── Pattern detection ─────────────────────────────────────────────────────
    detector = PatternDetector(patterns)
    gaps = detector.analyze_coverage_gaps(all_articles, strategy_id or 0)
    counts["gaps_detected"] = len(gaps)

    if not gaps:
        logger.info("detection_cycle: no coverage gaps detected")
        return counts

    logger.info("detection_cycle: %d gap(s) — generating theses", len(gaps))

    # ── LLM thesis + Signal write + Telegram alert ────────────────────────────
    llm = LLMSynthesizer(
        ollama_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        claude_key=settings.anthropic_api_key,
        claude_model=settings.claude_model,
    )
    notifier = TelegramNotifier()

    for gap in gaps[:3]:
        entity = gap.get("entity") or gap.get("topic", "")
        if not entity:
            continue

        gap_ratio = float(gap.get("gap_ratio", 1.0))
        confidence = min(gap_ratio / 10.0, 1.0)

        _write_signal(
            strategy_id=strategy_id,
            ticker=entity,
            signal_type="coverage_gap",
            confidence=confidence,
            raw=gap,
        )

        try:
            thesis = llm.generate_thesis(gap, strategy_id or 0)
        except Exception as exc:
            logger.warning("detection_cycle: thesis failed for %s: %s", entity, exc)
            thesis = (
                f"Coverage gap: {entity} — {gap.get('asia_count', 0)} Asian "
                f"vs {gap.get('western_count', 0)} Western articles "
                f"(gap ratio: {gap_ratio:.1f}x)."
            )

        opportunity = {
            "ticker": entity,
            "topic": "coverage_gap",
            "thesis": thesis,
            "western_count": gap.get("western_count", 0),
            "asia_count": gap.get("asia_count", 0),
            "gap_ratio": gap_ratio,
            "amount": 10_000.0,
            "stop_loss_pct": 5.0,
            "strategy_id": strategy_id,
            "confluence_score": confidence,
        }

        try:
            _async_notify(notifier.send_opportunity_alert(opportunity))
            counts["opportunities_sent"] += 1
        except Exception as exc:
            logger.error("detection_cycle: alert failed for %s: %s", entity, exc)

    logger.info(
        "Detection cycle complete for %s: %s",
        strategy_name,
        " | ".join(f"{k}={v}" for k, v in counts.items()),
    )
    return counts


def _write_signal(
    *,
    strategy_id: int | None,
    ticker: str,
    signal_type: str,
    confidence: float,
    raw: dict,
) -> None:
    """Insert a Signal row so detect_confluence() can aggregate across strategies."""
    from app.models import Signal

    try:
        with db_session() as db:
            row = Signal(
                strategy_id=strategy_id,
                ticker=ticker,
                signal_type=signal_type,
                confidence=round(min(max(confidence, 0.0), 1.0), 2),
                raw_data=json.dumps(raw),
            )
            db.add(row)
    except Exception as exc:
        logger.warning("_write_signal failed for %s: %s", ticker, exc)


def _fetch_articles_mentioning(db, ticker: str, hours: int = 24) -> list[dict]:
    """Return recent article records whose entities include *ticker*.

    Searches ``article_analysis.entities_detected`` (a JSON array stored as
    TEXT) for the ticker string.  Returns up to 20 results sorted newest first.
    """
    from app.models import ArticleRegistry, ArticleAnalysis

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(ArticleRegistry.title, ArticleAnalysis.sentiment_score,
                 ArticleAnalysis.thesis_notes, ArticleAnalysis.signal_strength)
        .join(ArticleAnalysis, ArticleRegistry.id == ArticleAnalysis.registry_id)
        .filter(
            ArticleAnalysis.analyzed_at >= cutoff,
            ArticleAnalysis.entities_detected.like(f'%"{ticker}"%'),
        )
        .order_by(ArticleAnalysis.analyzed_at.desc())
        .limit(20)
        .all()
    )

    return [
        {
            "title": r.title or "",
            "sentiment": float(r.sentiment_score or 0.0),
            "signal_strength": float(r.signal_strength or 0.0),
            "notes": r.thesis_notes or "",
        }
        for r in rows
    ]


def monitor_positions() -> None:
    """Check all open broker positions for exit signals and stop-loss proximity.

    For each open position:
    1. If unrealized P/L ≤ −4.5 % (approaching a 5 % stop), send a
       ``stop_loss`` alert immediately.
    2. Otherwise, fetch recent articles mentioning the ticker and pass them to
       the LLM exit-signal analyser.  If the analysis contains exit keywords
       (sell, reversal, bearish…), send a ``warning`` alert.
    3. Update the ``positions`` table with current broker prices via
       :func:`update_position_prices`.
    """
    from app.services.trading.alpaca_interface import AlpacaBroker
    from app.services.trading.broker_interface import BrokerError
    from app.services.analysis.llm_synthesizer import LLMSynthesizer
    from app.services.notifications.telegram_notifier import TelegramNotifier

    logger.info("monitor_positions: starting")

    try:
        broker = AlpacaBroker()
        positions = broker.get_current_positions()
    except BrokerError as exc:
        logger.error("monitor_positions: cannot fetch broker positions: %s", exc)
        return

    if not positions:
        logger.debug("monitor_positions: no open positions")
        return

    logger.info("monitor_positions: checking %d position(s)", len(positions))

    # Refresh prices in DB first
    update_position_prices()

    llm = LLMSynthesizer(
        ollama_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        claude_key=settings.anthropic_api_key,
        claude_model=settings.claude_model,
    )
    notifier = TelegramNotifier()

    _EXIT_KEYWORDS = frozenset({
        "exit", "sell", "reversal", "narrative shift",
        "bearish", "downgrade", "risk", "deteriorat",
    })
    _STOP_THRESHOLD = -4.5   # alert when within 0.5% of a 5% default stop

    for pos in positions:
        pos_dict = {
            "ticker": pos.ticker,
            "quantity": pos.quantity,
            "avg_entry_price": pos.avg_entry_price,
            "current_price": pos.current_price,
            "unrealized_pnl_pct": pos.unrealized_pnl_pct,
        }

        # ── Stop-loss proximity ───────────────────────────────────────────────
        if pos.unrealized_pnl_pct <= _STOP_THRESHOLD:
            logger.warning(
                "STOP PROXIMITY: %s at %.1f%% (threshold %.1f%%)",
                pos.ticker, pos.unrealized_pnl_pct, _STOP_THRESHOLD,
            )
            if not settings.dry_run:
                _async_notify(
                    notifier.send_position_alert(
                        pos_dict,
                        "stop_loss",
                        f"{pos.ticker} is {pos.unrealized_pnl_pct:.1f}% from entry — "
                        f"approaching stop-loss threshold.",
                    )
                )
            continue

        # ── LLM exit-signal analysis ──────────────────────────────────────────
        with db_session() as db:
            recent_articles = _fetch_articles_mentioning(db, pos.ticker, hours=24)

        if not recent_articles:
            logger.debug("monitor_positions: no recent articles for %s", pos.ticker)
            continue

        recent_text = "\n".join(
            f"- {a['title']} (sentiment={a['sentiment']:+.2f})"
            for a in recent_articles[:10]
        )

        try:
            analysis = llm.analyze_exit_signal(pos_dict, recent_text)
        except Exception as exc:
            logger.warning("Exit analysis failed for %s: %s", pos.ticker, exc)
            continue

        if any(kw in analysis.lower() for kw in _EXIT_KEYWORDS):
            logger.info("Exit signal detected for %s — sending alert", pos.ticker)
            if not settings.dry_run:
                _async_notify(
                    notifier.send_position_alert(pos_dict, "warning", analysis)
                )
        else:
            logger.debug("monitor_positions: %s — no exit signal", pos.ticker)

    logger.info("monitor_positions: done")


def detect_confluence() -> None:
    """Find tickers signalled by multiple strategies and alert on high confluence.

    Queries the ``signals`` table for the last 48 hours, groups by ticker, and
    computes a *confluence score*::

        confluence_score = unique_strategy_count × avg_confidence

    Tickers with score > 1.5 generate high-priority opportunity alerts with a
    boosted position-size recommendation (up to 2× the standard allocation).
    """
    from app.models import Signal
    from app.services.notifications.telegram_notifier import TelegramNotifier

    logger.info("detect_confluence: scanning signals from last 48h")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    with db_session() as db:
        signals = (
            db.query(Signal)
            .filter(
                Signal.created_at >= cutoff,
                Signal.ticker.is_not(None),
            )
            .all()
        )

    if not signals:
        logger.debug("detect_confluence: no signals found")
        return

    # ── Aggregate by ticker ───────────────────────────────────────────────────
    ticker_data: dict[str, dict] = {}
    for sig in signals:
        t = sig.ticker
        if t not in ticker_data:
            ticker_data[t] = {"strategies": set(), "confidences": [], "signal_types": []}
        ticker_data[t]["strategies"].add(sig.strategy_id)
        if sig.confidence is not None:
            ticker_data[t]["confidences"].append(float(sig.confidence))
        ticker_data[t]["signal_types"].append(sig.signal_type)

    # ── Score and filter ──────────────────────────────────────────────────────
    confluent = []
    for ticker, data in ticker_data.items():
        strategy_count = len(data["strategies"])
        if strategy_count < 2:
            continue
        avg_conf = (
            sum(data["confidences"]) / len(data["confidences"])
            if data["confidences"] else 0.5
        )
        score = strategy_count * avg_conf
        if score > 1.5:
            confluent.append({
                "ticker": ticker,
                "strategy_count": strategy_count,
                "avg_confidence": avg_conf,
                "confluence_score": score,
                "signal_types": sorted(set(t for t in data["signal_types"] if t)),
            })

    confluent.sort(key=lambda x: x["confluence_score"], reverse=True)

    if not confluent:
        logger.debug("detect_confluence: no confluent tickers (threshold > 1.5)")
        return

    logger.info(
        "detect_confluence: %d confluent ticker(s): %s",
        len(confluent),
        [c["ticker"] for c in confluent],
    )

    if settings.dry_run:
        for c in confluent:
            logger.info(
                "[DRY_RUN] Confluence: %s score=%.2f strategies=%d",
                c["ticker"], c["confluence_score"], c["strategy_count"],
            )
        return

    # ── Alert on top-3 confluent tickers ─────────────────────────────────────
    notifier = TelegramNotifier()
    for c in confluent[:3]:
        # Boost allocation up to 2× for high-confluence signals
        multiplier = min(c["confluence_score"] / 1.5, 2.0)
        types_str = ", ".join(c["signal_types"]) or "multiple"
        opportunity = {
            "ticker": c["ticker"],
            "topic": "confluence",
            "thesis": (
                f"Multi-strategy confluence: {c['ticker']} flagged by "
                f"{c['strategy_count']} strategies (signals: {types_str}). "
                f"Confidence score: {c['confluence_score']:.2f}."
            ),
            "western_count": 0,
            "asia_count": 0,
            "gap_ratio": 0.0,
            "amount": 10_000.0 * multiplier,
            "stop_loss_pct": 5.0,
            "strategy_id": None,
            "confluence_score": min(c["confluence_score"] / 3.0, 1.0),
        }
        try:
            _async_notify(notifier.send_opportunity_alert(opportunity))
        except Exception as exc:
            logger.error("detect_confluence: alert failed for %s: %s", c["ticker"], exc)

    logger.info("detect_confluence: done")


def check_stop_losses() -> None:
    """Alert when open positions are within 5 % of their stop-loss level.

    Fetches current positions from the broker and compares unrealized P/L
    against a configurable proximity threshold (−4.5 % = within 0.5 % of a
    default 5 % stop).  Sends a ``stop_loss`` Telegram alert for each at-risk
    position.
    """
    from app.services.trading.alpaca_interface import AlpacaBroker
    from app.services.trading.broker_interface import BrokerError
    from app.services.notifications.telegram_notifier import TelegramNotifier

    _PROXIMITY_THRESHOLD = -4.5   # alert at 90% of a 5% default stop

    logger.info("check_stop_losses: starting")

    try:
        broker = AlpacaBroker()
        positions = broker.get_current_positions()
    except BrokerError as exc:
        logger.error("check_stop_losses: broker error: %s", exc)
        return

    if not positions:
        logger.debug("check_stop_losses: no open positions")
        return

    notifier = TelegramNotifier()
    alerts_sent = 0

    for pos in positions:
        if pos.unrealized_pnl_pct > _PROXIMITY_THRESHOLD:
            continue   # safely above threshold

        logger.warning(
            "STOP PROXIMITY: %s at %.2f%% unrealized P/L (threshold %.1f%%)",
            pos.ticker, pos.unrealized_pnl_pct, _PROXIMITY_THRESHOLD,
        )

        if settings.dry_run:
            logger.info(
                "[DRY_RUN] Would send stop_loss alert for %s (%.1f%%)",
                pos.ticker, pos.unrealized_pnl_pct,
            )
            continue

        pos_dict = {
            "ticker": pos.ticker,
            "quantity": pos.quantity,
            "avg_entry_price": pos.avg_entry_price,
            "current_price": pos.current_price,
            "unrealized_pnl_pct": pos.unrealized_pnl_pct,
        }
        analysis = (
            f"{pos.ticker} is at {pos.unrealized_pnl_pct:.1f}% from entry. "
            f"Current: ${pos.current_price:,.2f} / Entry: ${pos.avg_entry_price:,.2f}. "
            f"Consider exiting to protect capital."
        )

        try:
            _async_notify(notifier.send_position_alert(pos_dict, "stop_loss", analysis))
            alerts_sent += 1
        except Exception as exc:
            logger.error("check_stop_losses: alert failed for %s: %s", pos.ticker, exc)

    logger.info(
        "check_stop_losses: %d/%d positions checked, %d alert(s) sent",
        len(positions), len(positions), alerts_sent,
    )


def update_position_prices() -> None:
    """Refresh ``current_price`` for every position in the DB from the broker.

    Queries all :class:`~app.models.position.Position` rows, fetches the
    matching broker position for each, and updates ``current_price``.  This
    drives the ``unrealized_pnl_pct`` property on the model without requiring
    a live broker call at display time.
    """
    from app.models import Position
    from app.services.trading.alpaca_interface import AlpacaBroker
    from app.services.trading.broker_interface import BrokerError

    logger.debug("update_position_prices: fetching broker positions")

    try:
        broker = AlpacaBroker()
        broker_positions = broker.get_current_positions()
    except BrokerError as exc:
        logger.error("update_position_prices: broker error: %s", exc)
        return

    if not broker_positions:
        logger.debug("update_position_prices: no broker positions")
        return

    price_map = {p.ticker: p.current_price for p in broker_positions}

    with db_session() as db:
        db_positions = db.query(Position).all()
        updated = 0
        for pos in db_positions:
            new_price = price_map.get(pos.ticker)
            if new_price is None:
                continue
            pos.current_price = new_price
            updated += 1

    logger.info(
        "update_position_prices: updated %d/%d position(s)",
        updated, len(db_positions),
    )


# ── Worker control (pause/resume via Telegram) ────────────────────────────────

def _is_worker_paused(mode: str) -> bool:
    """Return True if the bot has requested a pause for this worker mode.

    Checks the ``worker_controls`` table for a row with ``worker_name=mode``
    and ``paused=True``.  Missing rows are treated as not paused (running).
    Errors are logged and treated as not paused so the worker keeps going.
    """
    from app.models.worker_control import WorkerControl

    try:
        with db_session() as db:
            row = db.query(WorkerControl).filter(
                WorkerControl.worker_name == mode
            ).first()
            return bool(row and row.paused)
    except Exception as exc:
        logger.warning("_is_worker_paused: DB check failed (%s) — treating as running", exc)
        return False


# ── Async helper ──────────────────────────────────────────────────────────────

def _async_notify(coro) -> None:
    """Run an async coroutine from synchronous task context.

    Uses :func:`asyncio.run` which creates a fresh event loop.  If a loop is
    already running (unusual in worker context but possible in tests), falls
    back to a dedicated thread.
    """
    try:
        asyncio.run(coro)
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, coro).result(timeout=30)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Continuous worker loop.  Ctrl-C to stop.

    Usage::

        python -m app.workers.tasks <strategy-name> [--mode scrape|detect]

    Modes:
        scrape  (default) — RSS scrape + per-article LLM analysis.
                            Runs on the Mac Mini.
        detect  — RSS scrape (fast, no LLM per article) + PatternDetector
                  + thesis generation + Signal writes + Telegram alerts.
                  Runs on the Windows GPU host.
    """
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if len(sys.argv) < 2:
        logger.error("Usage: python -m app.workers.tasks <strategy-name> [--mode scrape|detect]")
        sys.exit(1)

    strategy_name = sys.argv[1]

    # Parse optional --mode flag (default: scrape)
    mode = "scrape"
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            mode = sys.argv[idx + 1]
    if mode not in ("scrape", "detect"):
        logger.error("Unknown --mode %r. Choose 'scrape' or 'detect'.", mode)
        sys.exit(1)

    interval_sec = settings.check_interval_minutes * 60

    logger.info("PAE worker starting — strategy=%s mode=%s interval=%ds dry_run=%s",
                strategy_name, mode, interval_sec, settings.dry_run)

    if not ping_db():
        logger.error("Cannot reach database at %s — aborting", settings.database_url)
        sys.exit(1)

    init_db()
    logger.info("Database schema initialised")

    from app.services.notifications.telegram_notifier import TelegramNotifier
    notifier = TelegramNotifier()

    cycle_fn = run_scrape_cycle if mode == "scrape" else run_detection_cycle

    while True:
        # ── Pause check (set via Telegram /pause command) ─────────────────────
        if _is_worker_paused(mode):
            logger.info("Worker paused via Telegram — sleeping 60s before re-check")
            try:
                time.sleep(60)
            except KeyboardInterrupt:
                logger.info("Shutting down — KeyboardInterrupt")
                break
            continue

        cycle_start = time.monotonic()
        try:
            counts = cycle_fn(strategy_name)
            elapsed = time.monotonic() - cycle_start
            if not settings.dry_run:
                _async_notify(notifier.send_cycle_summary(strategy_name, counts, elapsed))
        except KeyboardInterrupt:
            logger.info("Shutting down — KeyboardInterrupt")
            break
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unhandled error in %s cycle", mode)
            elapsed = time.monotonic() - cycle_start
            if not settings.dry_run:
                _async_notify(notifier.send_error_alert(strategy_name, str(exc)))

        logger.info("Sleeping %ds until next cycle…", interval_sec)
        try:
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            logger.info("Shutting down — KeyboardInterrupt")
            break


if __name__ == "__main__":
    main()
