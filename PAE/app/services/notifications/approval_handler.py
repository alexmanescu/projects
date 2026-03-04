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

Reply-based actions
-------------------
Reply YES to a 📡 suggestion message — approve a new Kalshi signal category
Reply NO  to a 📡 suggestion message — reject a new Kalshi signal category
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
            # Reply-based category vote: just send YES or NO as a reply to a suggestion message
            if command in ("YES", "NO") and update.message.reply_to_message:
                replied_id = update.message.reply_to_message.message_id
                handled = await self._handle_category_vote(replied_id, command, update)
                if handled:
                    return

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

            elif command == "ADDCAT" and len(parts) >= 2:
                term = " ".join(parts[1:]).title()
                await self.handle_addcat(term, update)

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

        Routes to KalshiInterface for market_type='kalshi', otherwise Alpaca.
        """
        from app.models import Opportunity, Trade
        from app.core.database import db_session
        from app.services.trading.position_manager import TradeValidationError

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

            market_type = opp.market_type or "us_stock"

        if market_type == "kalshi":
            await self._handle_kalshi_approval(opp)
            return

        # ── Equity approval (Alpaca / future Moomoo) ──────────────────────────
        broker, pm = self._get_broker_pm()

        with db_session() as db:
            opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()

            ticker = opp.ticker
            conviction = self._score_to_conviction(float(opp.confluence_score or 0.5))
            stop_loss_pct = float(opp.stop_loss_pct or 0.05)

            try:
                sizing = pm.validate_trade(ticker, conviction, stop_loss_pct)
            except TradeValidationError as exc:
                await self._notifier.send_message(
                    f"❌ Trade validation failed for <b>{ticker}</b>:\n{exc}"
                )
                opp.status = "rejected"
                return

            result = broker.execute_buy(ticker, sizing["shares"], stop_loss_pct)

            fill_price = result.filled_price
            stop_price = None
            if fill_price:
                stop_price = pm.calculate_stop_loss(fill_price, stop_loss_pct)

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

    async def _handle_kalshi_approval(self, opp) -> None:
        """Execute a Kalshi contract buy and confirm via Telegram."""
        from app.models import Trade
        from app.core.database import db_session
        from app.services.trading.kalshi_interface import KalshiInterface, KalshiError

        market_ticker = opp.kalshi_market_id or opp.ticker
        side = opp.kalshi_side or "yes"
        yes_price = int(opp.kalshi_yes_price or 50)
        contract_price = yes_price if side == "yes" else (100 - yes_price)
        suggested_amount = float(opp.suggested_amount or 5.0)
        count = max(1, int(suggested_amount / (contract_price / 100)))

        try:
            kalshi = KalshiInterface()
            result = kalshi.buy_contracts(
                market_ticker=market_ticker,
                side=side,
                count=count,
                max_price_cents=min(contract_price + 3, 99),  # 3¢ slippage tolerance
            )
        except KalshiError as exc:
            await self._notifier.send_message(
                f"❌ Kalshi order failed for <b>{market_ticker}</b>:\n{exc}"
            )
            return

        with db_session() as db:
            opp_row = db.query(opp.__class__).filter(opp.__class__.id == opp.id).first()
            if opp_row:
                opp_row.status = "approved"

            Trade.log_execution(
                db,
                ticker=market_ticker,
                action="buy",
                quantity=float(count),
                price=contract_price / 100.0,
                opportunity_id=opp.id,
                strategy_id=opp.primary_strategy_id,
                notes=f"kalshi_side={side} market={market_ticker} status={result.get('status')}",
            )

        logger.info(
            "Kalshi opportunity #%d approved: %s %s x%d @ %d¢",
            opp.id, market_ticker, side, count, contract_price,
        )
        await self._notifier.send_message(
            f"✅ <b>KALSHI ORDER{'  <i>(dry run)</i>' if result.get('status') == 'dry_run' else ''}</b>\n\n"
            f"<b>Market:</b> <code>{market_ticker}</code>\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>Contracts:</b> {count}\n"
            f"<b>Price:</b> {contract_price}¢\n"
            f"<b>Total cost:</b> ${count * contract_price / 100:.2f}\n"
            f"<b>Max payout:</b> ${count:.2f}"
        )

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

    # ── Category management ───────────────────────────────────────────────────

    async def handle_addcat(self, term: str, update: "Update") -> None:
        """Manually add and immediately activate a Kalshi signal category."""
        from datetime import datetime, timezone
        from app.models.kalshi_category import KalshiCategory
        from app.core.database import db_session

        with db_session() as db:
            existing = db.query(KalshiCategory).filter(
                KalshiCategory.term == term
            ).first()

            if existing:
                await update.message.reply_text(
                    f"⚠️ <b>{term}</b> is already <b>{existing.status}</b> — no change made.",
                    parse_mode="HTML",
                )
                if existing.status == "approved":
                    await self._spot_scan_kalshi(term)
                return

            db.add(KalshiCategory(
                term=term,
                category="manual",
                status="approved",
                source="manual ADDCAT command",
                approved_at=datetime.now(timezone.utc),
            ))

        logger.info("handle_addcat: manually approved %r", term)
        await update.message.reply_text(
            f"✅ <b>{term}</b> added and approved — scanning Kalshi now…",
            parse_mode="HTML",
        )
        await self._spot_scan_kalshi(term)

    async def _handle_category_vote(
        self, telegram_message_id: int, vote: str, update: "Update"
    ) -> bool:
        """Handle a YES/NO reply to a Kalshi signal-category suggestion.

        Returns ``True`` if the replied-to message was a category suggestion
        (even if already actioned).  Returns ``False`` when no matching
        category is found so the caller can fall through to trade approval.
        """
        from datetime import datetime, timezone
        from app.models.kalshi_category import KalshiCategory
        from app.core.database import db_session

        with db_session() as db:
            cat = (
                db.query(KalshiCategory)
                .filter(KalshiCategory.telegram_message_id == telegram_message_id)
                .first()
            )

            if cat is None:
                return False  # not a category suggestion — caller should fall through

            if cat.status != "suggested":
                await update.message.reply_text(
                    f"⚠️ Category <b>{cat.term}</b> is already <b>{cat.status}</b>.",
                    parse_mode="HTML",
                )
                return True

            if vote == "YES":
                cat.status = "approved"
                cat.approved_at = datetime.now(timezone.utc)
                approved_term = cat.term
                await update.message.reply_text(
                    f"✅ Category <b>{cat.term}</b> approved — scanning Kalshi now…",
                    parse_mode="HTML",
                )
                logger.info("Kalshi category %r approved via Telegram reply", cat.term)
            else:
                cat.status = "rejected"
                approved_term = None
                await update.message.reply_text(
                    f"🚫 Category <b>{cat.term}</b> rejected.",
                    parse_mode="HTML",
                )
                logger.info("Kalshi category %r rejected via Telegram reply", cat.term)

        if approved_term:
            await self._spot_scan_kalshi(approved_term)

        return True

    async def _spot_scan_kalshi(self, term: str) -> None:
        """Immediately scan Kalshi for *term* and alert on any high-probability markets."""
        from app.services.trading.kalshi_interface import KalshiInterface, KalshiError

        _YES_THRESHOLD = 65
        _SPORT_BLOCKED = (
            "sport", "entertainment", "pop culture", "award",
            "nba", "nfl", "nhl", "mlb", "nascar", "golf",
        )
        _SPORT_TITLE_KW = (
            "points", "rebounds", "assists", "touchdowns", "goals",
            "james", "lebron", "westbrook", "curry", "mahomes",
        )

        try:
            kalshi = KalshiInterface()
            markets = kalshi.find_markets(term, limit=20)
        except KalshiError as exc:
            logger.warning("_spot_scan_kalshi(%r) failed: %s", term, exc)
            await self._notifier.send_message(
                f"⚠️ Kalshi scan for <b>{term}</b> failed: {exc}"
            )
            return

        hits = []
        for m in markets:
            yes_price = int(m.get("yes_price", 50))
            if yes_price < _YES_THRESHOLD and yes_price > (100 - _YES_THRESHOLD):
                continue

            mkt_category = (m.get("category") or m.get("event_category") or "").lower()
            mkt_title = (m.get("title") or m.get("subtitle") or "").lower()
            ticker = m.get("ticker") or m.get("market_ticker", "")

            if (
                any(b in mkt_category for b in _SPORT_BLOCKED)
                or any(k in mkt_title for k in _SPORT_TITLE_KW)
                or "crosscategory" in ticker.lower()
                or ticker.upper().startswith("KXMVE")
            ):
                continue

            side = "YES" if yes_price >= _YES_THRESHOLD else "NO"
            price = yes_price if side == "YES" else (100 - yes_price)
            hits.append((ticker, side, price, m.get("title") or ticker))

        if not hits:
            await self._notifier.send_message(
                f"🔍 Spot scan for <b>{term}</b>: no markets above {_YES_THRESHOLD}% threshold right now."
            )
            return

        lines = [f"🔍 <b>SPOT SCAN — {term}</b>\n"]
        for ticker, side, price, title in hits[:5]:
            lines.append(f"• <code>{ticker}</code>\n  {title}\n  {side} @ {price}¢\n")
        await self._notifier.send_message("\n".join(lines))

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
            "• <code>HELP</code>   — Show this message\n\n"
            "<b>Signal Categories:</b>\n"
            "• <code>ADDCAT {term}</code> — Manually add a Kalshi search term and scan immediately\n"
            "• Reply <code>YES</code> or <code>NO</code> to a 📡 suggestion — Approve or reject a suggested category"
        )
