"""APScheduler configuration for PAE background workers.

Job schedule
------------
+---------------------+----------+------------------------------------------+
| Job ID              | Interval | Description                              |
+=====================+==========+==========================================+
| scrape_news         | 60 min   | Scrape + detect + alert for all strategies|
| monitor_positions   | 15 min   | Exit-signal checks on open positions     |
| detect_confluence   | 30 min   | Cross-strategy signal aggregation        |
| check_stops         |  5 min   | Stop-loss proximity alerts               |
| update_prices       |  1 min   | Refresh position prices from broker      |
+---------------------+----------+------------------------------------------+

Run directly::

    python -m app.workers.scheduler

Or import the ``scheduler`` object into ``scripts/run_workers.py`` for richer
logging and healthcheck integration.
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from app.workers.tasks import (
    scrape_all_strategies,
    monitor_positions,
    detect_confluence,
    check_stop_losses,
    update_position_prices,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Build scheduler
# ---------------------------------------------------------------------------

scheduler = BlockingScheduler(timezone="UTC")

# ── Scrape news every hour ────────────────────────────────────────────────────
scheduler.add_job(
    scrape_all_strategies,
    "interval",
    minutes=60,
    id="scrape_news",
    name="Scrape all strategies",
    max_instances=1,           # never run two scrape cycles concurrently
    coalesce=True,             # if missed, run once (not multiple catch-ups)
)

# ── Monitor positions every 15 minutes ───────────────────────────────────────
scheduler.add_job(
    monitor_positions,
    "interval",
    minutes=15,
    id="monitor_positions",
    name="Monitor open positions",
    max_instances=1,
    coalesce=True,
)

# ── Detect confluence every 30 minutes ───────────────────────────────────────
scheduler.add_job(
    detect_confluence,
    "interval",
    minutes=30,
    id="detect_confluence",
    name="Detect multi-strategy confluence",
    max_instances=1,
    coalesce=True,
)

# ── Check stop losses every 5 minutes ────────────────────────────────────────
scheduler.add_job(
    check_stop_losses,
    "interval",
    minutes=5,
    id="check_stops",
    name="Check stop-loss proximity",
    max_instances=1,
    coalesce=True,
)

# ── Update position prices every 1 minute ────────────────────────────────────
scheduler.add_job(
    update_position_prices,
    "interval",
    minutes=1,
    id="update_prices",
    name="Update position prices",
    max_instances=1,
    coalesce=True,
)

# ---------------------------------------------------------------------------
# Event listeners
# ---------------------------------------------------------------------------

def _on_job_executed(event) -> None:
    logger.debug("Job %r completed", event.job_id)


def _on_job_error(event) -> None:
    logger.error(
        "Job %r raised an exception: %s",
        event.job_id,
        event.exception,
        exc_info=event.traceback,
    )


scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)

# ---------------------------------------------------------------------------
# Direct entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting PAE scheduler directly…")
    scheduler.start()
