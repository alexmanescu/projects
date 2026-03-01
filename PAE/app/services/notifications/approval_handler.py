"""Telegram command router for trade approvals and portfolio management.

Handles inbound text messages from the configured chat and routes them to
the appropriate action.  All public methods are async (python-telegram-bot ≥ 21).

Supported commands
------------------
YES  {id}      — Approve opportunity and execute buy
NO   {id}      — Reject opportunity (logs for ML training)
INFO {id}      — Show full opportunity details
SELL {ticker}  — Close an open position
HOLD {ticker}  — Acknowledge alert, keep monitoring
STATUS         — Portfolio snapshot
HELP           — Command reference
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

from app.services.notifications.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class ApprovalHandler:
    """Route Telegram messages to trade-approval and portfolio-management actions.

    The broker and position manager are lazy-initialised on first use so the
    class can be instantiated (and tested) without the ``alpaca-py`` SDK
    being present.
    """

    def __init__(self, notifier: TelegramNotifier) -> None:
        self._notifier = notifier
        self._broker = None
        self._pm = None

    # ── Message router ────────────────────────────────────────────────────────

    async def handle_message(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """Parse inbound text and dispatch to the correct handler."""
        if update.message is None or update.message.text is None:
            return

        raw = update.message.text.strip()
        parts = raw.upper().split()
        command = parts[0] if parts else ""

        try:
            if command == "YES" and len(parts) >= 2:
                opp_id = int(parts[1])
                await update.message.reply_text(f"⏳ Processing approval for opportunity #{opp_id}…")
                await self.handle_approval(opp_id)

            elif command == "NO" and len(parts) >= 2:
                opp_id = int(parts[1])
                await self.handle_rejection(opp_id)
                await update.message.reply_text(f"🚫 Opportunity #{opp_id} rejected.")

            elif command == "INFO" and len(parts) >= 2:
                opp_id = int(parts[1])
                await self.handle_info_request(opp_id)

            elif command == "SELL" and len(parts) >= 2:
                ticker = parts[1]
                await update.message.reply_text(f"⏳ Closing position in {ticker}…")
                await self.handle_sell(ticker)

            elif command == "HOLD" and len(parts) >= 2:
                ticker = parts[1]
                await update.message.reply_text(
                    f"✋ Holding <b>{ticker}</b> — continuing to monitor.",
                    parse_mode="HTML",
                )

            elif command == "STATUS":
                await self.handle_status()

            elif command == "HELP":
                await update.message.reply_text(self._help_text(), parse_mode="HTML")

            else:
                await update.message.reply_text(
                    "Unknown command. Send <code>HELP</code> for available commands.",
                    parse_mode="HTML",
                )

        except ValueError:
            await update.message.reply_text(
                "❌ Invalid ID. Usage: <code>YES 123</code> or <code>NO 123</code>",
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Error handling message %r: %s", raw, exc, exc_info=True)
            await update.message.reply_text(f"❌ Unexpected error: {exc}")

    # ── Approval ──────────────────────────────────────────────────────────────

    async def handle_approval(self, opportunity_id: int) -> None:
        """Load opportunity, validate sizing, execute buy, update status.

        Steps:
        1. Load Opportunity from DB; abort if not found or already actioned.
        2. Derive conviction level from ``confluence_score``.
        3. Call ``PositionManager.validate_trade`` (raises on limit violations).
        4. Execute buy via broker.
        5. Log execution with ``Trade.log_execution``.
        6. Mark opportunity ``"approved"`` and send confirmation.
        """
        from app.models import Opportunity, Trade
        from app.core.database import db_session
        from app.services.trading.position_manager import TradeValidationError

        broker, pm = self._get_broker_pm()

        with db_session() as db:
            opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()

            if not opp:
                await self._notifier.send_message(
                    f"❌ Opportunity <b>#{opportunity_id}</b> not found.",
                )
                return

            if opp.status != "pending":
                await self._notifier.send_message(
                    f"⚠️ Opportunity <b>#{opportunity_id}</b> is already "
                    f"<b>{opp.status}</b> — cannot re-approve.",
                )
                return

            ticker = opp.ticker
            conviction = self._score_to_conviction(float(opp.confluence_score or 0.5))
            stop_loss_pct = float(opp.stop_loss_pct or 0.05)

            # Validate sizing and risk limits
            try:
                sizing = pm.validate_trade(ticker, conviction, stop_loss_pct)
            except TradeValidationError as exc:
                await self._notifier.send_message(
                    f"❌ Trade validation failed for <b>{ticker}</b>:\n{exc}"
                )
                opp.status = "rejected"
                return

            # Execute the buy order
            result = broker.execute_buy(ticker, sizing["shares"], stop_loss_pct)

            # Compute stop price for the trade log
            fill_price = result.filled_price
            stop_price = None
            if fill_price:
                stop_price = pm.calculate_stop_loss(fill_price, stop_loss_pct)

            # Record the trade
            Trade.log_execution(
                db,
                ticker=ticker,
                action="buy",
                quantity=sizing["shares"],
                price=fill_price or float(opp.suggested_price or 0),
                stop_loss=stop_price,
                opportunity_id=opportunity_id,
                strategy_id=opp.primary_strategy_id,
                notes=f"broker_order_id={result.order_id}",
            )

            opp.status = "approved"
            logger.info(
                "Opportunity #%d approved: %s x %.0f shares @ %s",
                opportunity_id, ticker, sizing["shares"], fill_price,
            )

        await self._notifier.send_execution_confirmation({
            "ticker": ticker,
            "action": "buy",
            "status": result.status,
            "quantity": sizing["shares"],
            "filled_price": result.filled_price,
            "stop_loss": stop_price,
        })

    # ── Rejection ─────────────────────────────────────────────────────────────

    async def handle_rejection(self, opportunity_id: int) -> None:
        """Mark opportunity as ``"rejected"`` for later ML training signal."""
        from app.models import Opportunity
        from app.core.database import db_session

        with db_session() as db:
            opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
            if not opp:
                await self._notifier.send_message(
                    f"❌ Opportunity <b>#{opportunity_id}</b> not found."
                )
                return
            opp.status = "rejected"
            logger.info("Opportunity #%d rejected by user", opportunity_id)

    # ── Info ──────────────────────────────────────────────────────────────────

    async def handle_info_request(self, opportunity_id: int) -> None:
        """Push full opportunity details to the chat."""
        from app.models import Opportunity
        from app.core.database import db_session

        with db_session() as db:
            opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()

            if not opp:
                await self._notifier.send_message(
                    f"❌ Opportunity <b>#{opportunity_id}</b> not found."
                )
                return

            amount_str = f"${opp.suggested_amount:,.0f}" if opp.suggested_amount else "N/A"
            sl_str = f"{float(opp.stop_loss_pct) * 100:.1f}%" if opp.stop_loss_pct else "N/A"
            created_str = (
                opp.created_at.strftime("%Y-%m-%d %H:%M UTC")
                if opp.created_at else "N/A"
            )
            score_str = f"{opp.confluence_score:.2f}" if opp.confluence_score else "N/A"

        message = (
            f"📋 <b>OPPORTUNITY DETAILS #{opp.id}</b>\n\n"
            f"<b>Ticker:</b> {opp.ticker}\n"
            f"<b>Status:</b> {opp.status}\n"
            f"<b>Confluence Score:</b> {score_str}\n\n"
            f"<b>Full Thesis:</b>\n{opp.thesis or 'N/A'}\n\n"
            f"<b>Coverage Analysis:</b>\n{opp.coverage_analysis or 'N/A'}\n\n"
            f"<b>Catalyst:</b>\n{opp.catalyst or 'N/A'}\n\n"
            f"<b>Suggested Position:</b>\n"
            f"• Amount: {amount_str}\n"
            f"• Stop Loss: {sl_str}\n"
            f"• Created: {created_str}"
        )
        await self._notifier.send_message(message)

    # ── Sell ──────────────────────────────────────────────────────────────────

    async def handle_sell(self, ticker: str) -> None:
        """Close the position for *ticker* and remove it from the DB."""
        from app.models import Position, Trade
        from app.core.database import db_session

        broker, _ = self._get_broker_pm()

        with db_session() as db:
            pos = db.query(Position).filter(Position.ticker == ticker).first()

            if not pos:
                await self._notifier.send_message(
                    f"❌ No open position found for <b>{ticker}</b>."
                )
                return

            shares = float(pos.quantity or 0)
            if shares <= 0:
                await self._notifier.send_message(
                    f"❌ Position for <b>{ticker}</b> has zero shares."
                )
                return

            result = broker.execute_sell(ticker, shares)

            Trade.log_execution(
                db,
                ticker=ticker,
                action="sell",
                quantity=shares,
                price=result.filled_price or 0.0,
                notes=f"broker_order_id={result.order_id}",
            )

            db.delete(pos)
            logger.info("Position %s closed: %.0f shares @ %s", ticker, shares, result.filled_price)

        await self._notifier.send_execution_confirmation({
            "ticker": ticker,
            "action": "sell",
            "status": result.status,
            "quantity": shares,
            "filled_price": result.filled_price,
        })

    # ── Status ────────────────────────────────────────────────────────────────

    async def handle_status(self) -> None:
        """Push a full portfolio snapshot to the chat."""
        broker, _ = self._get_broker_pm()

        try:
            account = broker.get_account_info()
            positions = broker.get_current_positions()
        except Exception as exc:
            await self._notifier.send_message(f"❌ Failed to fetch portfolio status: {exc}")
            return

        pos_lines = []
        for p in positions:
            emoji = "🟢" if p.unrealized_pnl_pct >= 0 else "🔴"
            pos_lines.append(
                f"{emoji} <b>{p.ticker}</b>: {p.quantity:.0f} sh "
                f"@ ${p.current_price:,.2f} ({p.unrealized_pnl_pct:+.1f}%)"
            )

        positions_text = "\n".join(pos_lines) if pos_lines else "No open positions"
        total_pnl = sum(p.unrealized_pnl for p in positions)
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        mode_label = "Paper Trading" if account.is_paper else "🔴 LIVE TRADING"

        message = (
            f"📊 <b>PORTFOLIO STATUS</b>\n\n"
            f"<b>Account:</b>\n"
            f"• Portfolio Value: ${account.portfolio_value:,.2f}\n"
            f"• Cash: ${account.cash:,.2f}\n"
            f"• Buying Power: ${account.buying_power:,.2f}\n"
            f"• Mode: {mode_label}\n\n"
            f"<b>Positions ({len(positions)}):</b>\n"
            f"{positions_text}\n\n"
            f"<b>Total Unrealized P/L:</b> {pnl_emoji} ${total_pnl:+,.2f}"
        )
        await self._notifier.send_message(message)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_broker_pm(self):
        """Lazy-init broker and position manager (skips SDK import at class init)."""
        if self._broker is None:
            from app.services.trading.alpaca_interface import AlpacaBroker
            from app.services.trading.position_manager import PositionManager

            self._broker = AlpacaBroker()
            self._pm = PositionManager(self._broker)
        return self._broker, self._pm

    @staticmethod
    def _score_to_conviction(score: float) -> str:
        """Map a 0–1 confluence score to a conviction label."""
        if score >= 0.70:
            return "high"
        if score >= 0.50:
            return "medium"
        return "low"

    @staticmethod
    def _help_text() -> str:
        return (
            "📖 <b>AVAILABLE COMMANDS</b>\n\n"
            "<b>Opportunities:</b>\n"
            "• <code>YES {id}</code> — Approve and execute trade\n"
            "• <code>NO {id}</code>  — Reject opportunity\n"
            "• <code>INFO {id}</code> — Show full details\n\n"
            "<b>Positions:</b>\n"
            "• <code>SELL {ticker}</code> — Close position\n"
            "• <code>HOLD {ticker}</code> — Acknowledge alert, keep monitoring\n\n"
            "<b>Portfolio:</b>\n"
            "• <code>STATUS</code> — Portfolio summary\n"
            "• <code>HELP</code>   — Show this message"
        )
