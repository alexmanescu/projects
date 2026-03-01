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

from telegram.ext import Application, MessageHandler, filters

from app.core.config import settings
from app.services.notifications.approval_handler import ApprovalHandler
from app.services.notifications.telegram_notifier import TelegramNotifier


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

    # Route all non-command text messages to the approval handler.
    # Bot-command messages (starting with '/') are explicitly excluded so
    # standard Telegram bot commands don't conflict with our text protocol.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handler.handle_message)
    )

    logger.info("Bot is listening — send HELP to see available commands")

    # run_polling blocks until the process is killed or SIGINT/SIGTERM received.
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
