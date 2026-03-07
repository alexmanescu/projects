#!/usr/bin/env python3
"""PAE background worker process — entry point for the APScheduler loop.

Usage::

    python scripts/run_workers.py

Logs go to both ``logs/workers.log`` (rotating, 10 MB × 3 backups) and
stdout so container/launchd/systemd output is always visible.

Pre-flight health check
-----------------------
Before starting the scheduler the script checks database reachability,
Ollama availability, and broker connectivity.  Missing or degraded components
are logged as warnings but do not prevent startup (except a failed database
connection, which is fatal).
"""

import logging
import logging.handlers
import sys
from pathlib import Path

# ── Ensure PAE package root is importable ─────────────────────────────────────
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# ── Logging setup ─────────────────────────────────────────────────────────────
_LOG_DIR = _repo_root / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_file_handler = logging.handlers.RotatingFileHandler(
    _LOG_DIR / "workers.log",
    maxBytes=10 * 1024 * 1024,   # 10 MB
    backupCount=3,
    encoding="utf-8",
)
_stream_handler = logging.StreamHandler(sys.stdout)

_fmt = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_file_handler.setFormatter(_fmt)
_stream_handler.setFormatter(_fmt)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_file_handler, _stream_handler],
)

logger = logging.getLogger(__name__)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    from app.core.config import settings
    from app.core.database import init_db
    from app.workers.health import check_system_health
    from app.workers.scheduler import scheduler

    logger.info(
        "PAE workers starting — dry_run=%s paper_trading=%s",
        settings.dry_run,
        settings.paper_trading,
    )

    # ── Pre-flight health check ───────────────────────────────────────────────
    logger.info("Running pre-flight health check…")
    health = check_system_health()
    for component, status in health.items():
        if component in ("overall", "details"):
            continue
        level = logging.INFO if status == "ok" else logging.WARNING
        logger.log(level, "  %-10s → %s", component, status)

    if health.get("database") == "unavailable":
        logger.critical("Database is unreachable — cannot start workers. Aborting.")
        sys.exit(1)

    if health.get("overall") == "unhealthy":
        logger.warning("System health is UNHEALTHY — starting anyway with degraded functionality")
    elif health.get("overall") == "degraded":
        logger.warning("System health is DEGRADED — some features may not work")

    # ── Initialise DB schema ──────────────────────────────────────────────────
    try:
        init_db()
        logger.info("Database schema verified/initialised")
    except Exception as exc:
        logger.critical("init_db() failed: %s — aborting", exc)
        sys.exit(1)

    # ── Print job schedule ────────────────────────────────────────────────────
    logger.info("Scheduled jobs:")
    for job in scheduler.get_jobs():
        next_run = getattr(job, "next_run_time", None) or getattr(job, "next_fire_time", None)
        logger.info("  %-25s next run: %s", job.name, next_run)

    # ── Start scheduler (blocking) ────────────────────────────────────────────
    logger.info("Starting PAE workers…")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down PAE workers…")
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        logger.info("PAE workers stopped.")


if __name__ == "__main__":
    main()
