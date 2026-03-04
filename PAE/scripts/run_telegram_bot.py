#!/usr/bin/env python3
"""Standalone Telegram bot — listens for approval commands and acts on them.

Usage::

    python scripts/run_telegram_bot.py

The process runs until interrupted (Ctrl-C).  All configuration is read from
environment variables (or a ``.env`` file in the project root).

Required env vars
-----------------
TELEGRAM_BOT_TOKEN    — Bot token from @BotFather
TELEGRAM_CHAT_ID      — The chat ID that is allowed to issue commands

Optional
--------
DRY_RUN=True          — Simulate trades without submitting real orders (default)
PAPER_TRADING=True    — Use Alpaca paper endpoint (default)
LOG_LEVEL=INFO        — Logging verbosity
"""

import logging
import sys
from pathlib import Path

# Ensure the PAE package root is importable when the script is run directly
# from the project directory (e.g. ``python scripts/run_telegram_bot.py``).
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.core.config import settings
from app.core.database import db_session, init_db
from app.services.notifications.approval_handler import ApprovalHandler
from app.services.notifications.telegram_notifier import TelegramNotifier

_VALID_WORKERS = ("scrape", "detect")


def _set_paused(worker_name: str, paused: bool) -> None:
    from app.models.worker_control import WorkerControl
    with db_session() as db:
        row = db.query(WorkerControl).filter(WorkerControl.worker_name == worker_name).first()
        if row:
            row.paused = paused
            row.updated_by = "telegram"
        else:
            db.add(WorkerControl(worker_name=worker_name, paused=paused, updated_by="telegram"))


def _get_all_states() -> dict:
    from app.models.worker_control import WorkerControl
    with db_session() as db:
        rows = db.query(WorkerControl).filter(WorkerControl.worker_name.in_(_VALID_WORKERS)).all()
        states = {w: False for w in _VALID_WORKERS}
        for row in rows:
            states[row.worker_name] = row.paused
        return states


async def cmd_wstatus(update, context) -> None:
    states = _get_all_states()
    lines = ["🖥 <b>Worker Status</b>", ""]
    for name in _VALID_WORKERS:
        icon = "⏸ PAUSED" if states.get(name) else "▶️ running"
        lines.append(f"• <b>{name}</b>: {icon}")
    await update.message.reply_html("\n".join(lines))


async def cmd_pause(update, context) -> None:
    args = context.args
    targets = [args[0]] if args and args[0] in _VALID_WORKERS else list(_VALID_WORKERS)
    for worker in targets:
        _set_paused(worker, True)
    names = " + ".join(targets)
    await update.message.reply_html(
        f"⏸ <b>{names}</b> paused — will stop after current cycle completes.\n"
        f"Send /resume {targets[0]} to restart."
    )


async def cmd_resume(update, context) -> None:
    args = context.args
    targets = [args[0]] if args and args[0] in _VALID_WORKERS else list(_VALID_WORKERS)
    for worker in targets:
        _set_paused(worker, False)
    names = " + ".join(targets)
    await update.message.reply_html(f"▶️ <b>{names}</b> resumed — will run on next cycle check.")


def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    # ── Pre-flight checks ─────────────────────────────────────────────────────
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set — cannot start bot")
        sys.exit(1)

    if not settings.telegram_chat_id:
        logger.error("TELEGRAM_CHAT_ID is not set — cannot start bot")
        sys.exit(1)

    init_db()

    logger.info(
        "PAE Telegram bot starting (dry_run=%s, paper_trading=%s)",
        settings.dry_run,
        settings.paper_trading,
    )

    # ── Wire up services ──────────────────────────────────────────────────────
    notifier = TelegramNotifier()
    handler = ApprovalHandler(notifier)

    # ── Build application ─────────────────────────────────────────────────────
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Slash commands — worker control
    application.add_handler(CommandHandler("wstatus", cmd_wstatus))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))

    # Text commands — trade approvals, portfolio management
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handler.handle_message)
    )

    logger.info("Bot is listening — send HELP to see available commands")

    # run_polling blocks until the process is killed or SIGINT/SIGTERM received.
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
