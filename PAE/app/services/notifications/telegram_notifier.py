"""Telegram notification sender for PAE signals and trade confirmations.

Responsibilities:
- Push formatted HTML messages to the configured chat via the Bot API.
- Persist new opportunities to the database and return their IDs so the
  approval handler can reference them in later commands.
- Format alerts for positions and execution confirmations.

All public methods are async and handle their own exceptions, returning
a falsy value or logging the error rather than propagating, so callers
never crash on a notification failure.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send messages to a single Telegram chat via the Bot API.

    Uses ``telegram.Bot`` (python-telegram-bot ≥ 21) in an async-context-manager
    pattern so the underlying HTTPS session is properly managed.
    """

    def __init__(self) -> None:
        self._token = settings.telegram_bot_token
        self._chat_id = settings.telegram_chat_id

    # ── Core send ─────────────────────────────────────────────────────────────

    async def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send *message* to the configured chat.

        Args:
            message: Text body (HTML or MarkdownV2 depending on *parse_mode*).
            parse_mode: ``"HTML"`` (default) or ``"MarkdownV2"``.

        Returns:
            ``True`` on success, ``False`` if the API call failed.
        """
        if not self._token or not self._chat_id:
            logger.warning(
                "Telegram not configured (token=%s, chat_id=%s) — message skipped",
                bool(self._token), bool(self._chat_id),
            )
            return False

        try:
            from telegram import Bot

            async with Bot(self._token) as bot:
                await bot.send_message(
                    chat_id=self._chat_id,
                    text=message,
                    parse_mode=parse_mode,
                )
            return True
        except Exception as exc:
            logger.error("send_message failed: %s", exc)
            return False

    # ── Opportunity alert ─────────────────────────────────────────────────────

    async def send_opportunity_alert(self, opportunity: dict) -> int:
        """Persist *opportunity* to the DB, then push a formatted alert.

        Expected keys in *opportunity*:
        - ``ticker``       — stock ticker symbol
        - ``topic``        — news topic / catalyst label
        - ``thesis``       — LLM-generated trade thesis text
        - ``western_count`` — number of western-media articles
        - ``asia_count``   — number of asian-media articles
        - ``gap_ratio``    — coverage-gap multiplier
        - ``amount``       — suggested dollar allocation
        - ``stop_loss_pct`` — stop distance as a percentage (e.g. ``5.0``)
        - ``strategy_id``  — FK to strategies table (optional)
        - ``confluence_score`` — 0–1 signal confidence (optional)

        Returns:
            The newly created ``Opportunity.id`` (always ≥ 1 on success,
            ``-1`` if the DB write failed).
        """
        opp_id = self._save_opportunity(opportunity)
        if opp_id < 0:
            logger.error("Skipping alert — failed to save opportunity")
            return opp_id

        ticker = opportunity.get("ticker", "UNKNOWN")
        topic = opportunity.get("topic", "")
        thesis = opportunity.get("thesis", "")
        western_count = opportunity.get("western_count", 0)
        asia_count = opportunity.get("asia_count", 0)
        gap_ratio = opportunity.get("gap_ratio", 0.0)
        amount = opportunity.get("amount", 0.0)
        stop_loss_pct = opportunity.get("stop_loss_pct", 5.0)
        max_loss = amount * stop_loss_pct / 100

        thesis_preview = (thesis[:300] + "...") if len(thesis) > 300 else thesis

        message = (
            f"🎯 <b>OPPORTUNITY DETECTED</b>\n\n"
            f"<b>Ticker:</b> {ticker}\n"
            f"<b>Topic:</b> {topic}\n\n"
            f"<b>Thesis:</b>\n{thesis_preview}\n\n"
            f"<b>Coverage Analysis:</b>\n"
            f"• Western: {western_count} articles\n"
            f"• Asian: {asia_count} articles\n"
            f"• Gap: {gap_ratio:.1f}x\n\n"
            f"<b>Suggested Position:</b>\n"
            f"• Amount: ${amount:,.0f}\n"
            f"• Stop Loss: {stop_loss_pct:.1f}%\n"
            f"• Max Loss: ${max_loss:,.0f}\n\n"
            f"<b>Commands:</b>\n"
            f"Reply: <code>YES {opp_id}</code>\n"
            f"Skip: <code>NO {opp_id}</code>\n"
            f"Details: <code>INFO {opp_id}</code>"
        )

        await self.send_message(message)
        return opp_id

    # ── Position alert ────────────────────────────────────────────────────────

    async def send_position_alert(
        self, position: dict, alert_type: str, analysis: str
    ) -> bool:
        """Push a position-monitoring alert.

        Args:
            position: Dict with ``ticker``, ``quantity``, ``avg_entry_price``,
                ``current_price``, ``unrealized_pnl_pct``.
            alert_type: One of ``"warning"``, ``"stop_loss"``, ``"profit_target"``.
            analysis: Free-text analysis from the LLM or rule engine.

        Returns:
            Result of :meth:`send_message`.
        """
        ticker = position.get("ticker", "UNKNOWN")
        qty = position.get("quantity", 0)
        entry = position.get("avg_entry_price", 0.0)
        current = position.get("current_price", 0.0)
        pnl_pct = position.get("unrealized_pnl_pct", 0.0)

        icons = {
            "warning": "⚠️",
            "stop_loss": "🛑",
            "profit_target": "✅",
        }
        icon = icons.get(alert_type, "📊")
        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
        type_label = alert_type.replace("_", " ").title()

        message = (
            f"{icon} <b>POSITION ALERT: {ticker}</b>\n\n"
            f"<b>Type:</b> {type_label}\n\n"
            f"<b>Position:</b>\n"
            f"• Shares: {qty}\n"
            f"• Entry: ${entry:,.2f}\n"
            f"• Current: ${current:,.2f}\n"
            f"• P/L: {pnl_emoji} {pnl_pct:+.1f}%\n\n"
            f"<b>Analysis:</b>\n{analysis}\n\n"
            f"<b>Actions:</b>\n"
            f"Close: <code>SELL {ticker}</code>\n"
            f"Keep: <code>HOLD {ticker}</code>"
        )
        return await self.send_message(message)

    # ── Execution confirmation ────────────────────────────────────────────────

    async def send_execution_confirmation(self, result: dict) -> bool:
        """Push a trade execution success or failure notification.

        Args:
            result: Dict with ``ticker``, ``action``, ``status``,
                ``quantity``, ``filled_price`` (or ``None``),
                ``stop_loss`` (optional), ``error`` (on failure).

        Returns:
            Result of :meth:`send_message`.
        """
        ticker = result.get("ticker", "UNKNOWN")
        action = result.get("action", "buy").upper()
        status = result.get("status", "unknown")

        if status in {"filled", "dry_run"}:
            filled_price = result.get("filled_price")
            quantity = result.get("quantity", 0)
            stop_loss = result.get("stop_loss")
            price_str = f"${filled_price:,.2f}" if filled_price else "(pending fill)"
            stop_str = f"${stop_loss:,.2f}" if stop_loss else "N/A"
            dry_note = " <i>(dry run)</i>" if status == "dry_run" else ""

            message = (
                f"✅ <b>ORDER EXECUTED{dry_note}</b>\n\n"
                f"<b>Action:</b> {action} {ticker}\n"
                f"<b>Shares:</b> {quantity}\n"
                f"<b>Fill Price:</b> {price_str}\n"
                f"<b>Stop Loss:</b> {stop_str}\n"
                f"<b>Status:</b> {status}"
            )
        else:
            error = result.get("error", "Unknown error")
            message = (
                f"❌ <b>ORDER FAILED</b>\n\n"
                f"<b>Action:</b> {action} {ticker}\n"
                f"<b>Error:</b> {error}\n"
                f"<b>Status:</b> {status}"
            )

        return await self.send_message(message)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _save_opportunity(self, opportunity: dict) -> int:
        """Write *opportunity* to the DB and return the new row ID.

        Returns ``-1`` on any error so callers can check without try/except.
        """
        try:
            from app.models import Opportunity
            from app.core.database import db_session

            coverage = json.dumps({
                "western_count": opportunity.get("western_count", 0),
                "asia_count": opportunity.get("asia_count", 0),
                "gap_ratio": opportunity.get("gap_ratio", 0.0),
            })

            with db_session() as db:
                row = Opportunity(
                    ticker=opportunity.get("ticker", "UNKNOWN"),
                    thesis=opportunity.get("thesis"),
                    coverage_analysis=coverage,
                    catalyst=opportunity.get("topic"),
                    suggested_amount=opportunity.get("amount"),
                    stop_loss_pct=opportunity.get("stop_loss_pct"),
                    confluence_score=opportunity.get("confluence_score"),
                    primary_strategy_id=opportunity.get("strategy_id"),
                    status="pending",
                )
                db.add(row)
                db.flush()
                opp_id = row.id

            logger.info("Saved opportunity #%d for %s", opp_id, opportunity.get("ticker"))
            return opp_id

        except Exception as exc:
            logger.error("_save_opportunity failed: %s", exc)
            return -1
