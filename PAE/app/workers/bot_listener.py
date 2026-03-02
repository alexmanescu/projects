"""Telegram bot command listener for PAE worker control.

Runs as a separate process alongside the workers.  Receives commands from the
configured Telegram chat and writes pause/resume flags to the ``worker_controls``
DB table, which the workers check at the top of every cycle.

Usage::

    python -m app.workers.bot_listener

Commands:
    /status             — show current pause state of all workers
    /pause scrape       — pause the Mac Mini scrape worker
    /pause detect       — pause the Windows detection worker
    /pause              — pause both workers
    /resume scrape      — resume the scrape worker
    /resume detect      — resume the detection worker
    /resume             — resume both workers
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.core.database import db_session, init_db

logger = logging.getLogger(__name__)

_VALID_WORKERS = ("scrape", "detect")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _set_paused(worker_name: str, paused: bool) -> None:
    """Upsert a WorkerControl row for *worker_name*."""
    from app.models.worker_control import WorkerControl

    with db_session() as db:
        row = db.query(WorkerControl).filter(
            WorkerControl.worker_name == worker_name
        ).first()
        if row:
            row.paused = paused
            row.updated_by = "telegram"
        else:
            db.add(WorkerControl(
                worker_name=worker_name,
                paused=paused,
                updated_by="telegram",
            ))


def _get_all_states() -> dict[str, bool]:
    """Return {worker_name: paused} for all known workers."""
    from app.models.worker_control import WorkerControl

    with db_session() as db:
        rows = db.query(WorkerControl).filter(
            WorkerControl.worker_name.in_(_VALID_WORKERS)
        ).all()
        states = {w: False for w in _VALID_WORKERS}   # default: running
        for row in rows:
            states[row.worker_name] = row.paused
        return states


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_status(update, context) -> None:
    """Handle /status — show current worker states."""
    states = _get_all_states()
    lines = ["🖥 <b>Worker Status</b>", ""]
    for name in _VALID_WORKERS:
        icon = "⏸ PAUSED" if states.get(name) else "▶️ running"
        lines.append(f"• <b>{name}</b>: {icon}")
    await update.message.reply_html("\n".join(lines))


async def cmd_pause(update, context) -> None:
    """Handle /pause [scrape|detect] — pause one or both workers."""
    args = context.args
    targets = [args[0]] if args and args[0] in _VALID_WORKERS else list(_VALID_WORKERS)

    for worker in targets:
        _set_paused(worker, True)
        logger.info("bot_listener: paused worker %r", worker)

    names = " + ".join(targets)
    await update.message.reply_html(
        f"⏸ <b>{names}</b> paused — will stop after current cycle completes.\n"
        f"Send /resume {targets[0]} to restart."
    )


async def cmd_resume(update, context) -> None:
    """Handle /resume [scrape|detect] — resume one or both workers."""
    args = context.args
    targets = [args[0]] if args and args[0] in _VALID_WORKERS else list(_VALID_WORKERS)

    for worker in targets:
        _set_paused(worker, False)
        logger.info("bot_listener: resumed worker %r", worker)

    names = " + ".join(targets)
    await update.message.reply_html(
        f"▶️ <b>{names}</b> resumed — will run on next cycle check."
    )


async def cmd_help(update, context) -> None:
    """Handle /help."""
    await update.message.reply_html(
        "📋 <b>PAE Bot Commands</b>\n\n"
        "/status — show worker states\n"
        "/pause scrape — pause Mac Mini scraper\n"
        "/pause detect — pause Windows detector\n"
        "/pause — pause both\n"
        "/resume scrape — resume Mac Mini scraper\n"
        "/resume detect — resume Windows detector\n"
        "/resume — resume both"
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Start the bot in long-polling mode.  Ctrl-C to stop."""
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set — cannot start bot listener")
        return

    init_db()

    from telegram.ext import Application, CommandHandler

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))  # /start shows help

    logger.info("PAE bot listener starting (polling)…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
