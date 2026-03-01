"""Tests for Telegram notifier and approval handler."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

pytestmark = pytest.mark.asyncio


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_opportunity_dict(**overrides) -> dict:
    base = {
        "ticker": "NVDA",
        "topic": "semiconductor_policy",
        "thesis": "NVIDIA benefits from export restrictions on SMIC.",
        "western_count": 1,
        "asia_count": 7,
        "gap_ratio": 7.0,
        "amount": 10_000.0,
        "stop_loss_pct": 5.0,
        "strategy_id": 1,
        "confluence_score": 0.75,
    }
    base.update(overrides)
    return base


def _make_opportunity_row(**overrides):
    row = MagicMock()
    row.id = overrides.get("id", 42)
    row.ticker = overrides.get("ticker", "NVDA")
    row.thesis = overrides.get("thesis", "Full thesis text here.")
    row.coverage_analysis = overrides.get("coverage_analysis", '{"western_count": 1}')
    row.catalyst = overrides.get("catalyst", "chip ban")
    row.suggested_amount = overrides.get("suggested_amount", 10_000.0)
    row.stop_loss_pct = overrides.get("stop_loss_pct", 0.05)
    row.confluence_score = overrides.get("confluence_score", 0.75)
    row.primary_strategy_id = overrides.get("primary_strategy_id", 1)
    row.status = overrides.get("status", "pending")
    row.created_at = MagicMock()
    row.created_at.strftime.return_value = "2025-01-01 12:00 UTC"
    return row


def _make_position_row(ticker: str = "NVDA", quantity: float = 50.0):
    pos = MagicMock()
    pos.ticker = ticker
    pos.quantity = quantity
    pos.avg_entry_price = 100.0
    return pos


@contextmanager
def _mock_db_session(query_result=None):
    """Context manager that yields a mock DB session."""
    session = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = query_result
    q.all.return_value = [query_result] if query_result else []
    session.query.return_value = q
    session.add = MagicMock()
    session.flush = MagicMock()
    session.delete = MagicMock()
    yield session


def _patch_db(result=None):
    """Return a patch for db_session that yields a mock session."""
    cm = MagicMock()
    session = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = result
    session.query.return_value = q
    session.add = MagicMock()
    session.flush = MagicMock()
    session.delete = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)
    return cm, session


# ── TelegramNotifier.send_message ─────────────────────────────────────────────

class TestSendMessage:
    async def test_returns_true_on_success(self):
        mock_bot = AsyncMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)
        mock_bot.send_message = AsyncMock()

        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "TOKEN"
            ms.telegram_chat_id = "CHAT"
            with patch("telegram.Bot", return_value=mock_bot):
                from app.services.notifications.telegram_notifier import TelegramNotifier
                notifier = TelegramNotifier()
                result = await notifier.send_message("Hello")

        assert result is True

    async def test_returns_false_when_not_configured(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = ""
            ms.telegram_chat_id = ""
            from app.services.notifications.telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier()
            result = await notifier.send_message("Hello")

        assert result is False

    async def test_returns_false_on_api_error(self):
        mock_bot = AsyncMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)
        mock_bot.send_message = AsyncMock(side_effect=Exception("Network error"))

        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "TOKEN"
            ms.telegram_chat_id = "CHAT"
            with patch("telegram.Bot", return_value=mock_bot):
                from app.services.notifications.telegram_notifier import TelegramNotifier
                notifier = TelegramNotifier()
                result = await notifier.send_message("Hello")

        assert result is False

    async def test_passes_parse_mode_to_bot(self):
        mock_bot = AsyncMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)
        mock_bot.send_message = AsyncMock()

        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            with patch("telegram.Bot", return_value=mock_bot):
                from app.services.notifications.telegram_notifier import TelegramNotifier
                notifier = TelegramNotifier()
                await notifier.send_message("test", parse_mode="MarkdownV2")

        mock_bot.send_message.assert_called_once_with(
            chat_id="C", text="test", parse_mode="MarkdownV2"
        )


# ── TelegramNotifier.send_opportunity_alert ───────────────────────────────────

class TestSendOpportunityAlert:
    def _make_notifier_with_mocked_send(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            from app.services.notifications.telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier()
        notifier.send_message = AsyncMock(return_value=True)
        return notifier

    async def test_returns_opportunity_id(self):
        notifier = self._make_notifier_with_mocked_send()
        cm, session = _patch_db()
        mock_row = MagicMock()
        mock_row.id = 99

        with patch("app.services.notifications.telegram_notifier.db_session", return_value=cm):
            with patch("app.services.notifications.telegram_notifier.Opportunity", return_value=mock_row):
                opp_id = await notifier.send_opportunity_alert(_make_opportunity_dict())

        assert opp_id == 99

    async def test_sends_message_with_ticker(self):
        notifier = self._make_notifier_with_mocked_send()
        cm, session = _patch_db()
        mock_row = MagicMock()
        mock_row.id = 10

        with patch("app.services.notifications.telegram_notifier.db_session", return_value=cm):
            with patch("app.services.notifications.telegram_notifier.Opportunity", return_value=mock_row):
                await notifier.send_opportunity_alert(_make_opportunity_dict(ticker="AMD"))

        sent_text = notifier.send_message.call_args[0][0]
        assert "AMD" in sent_text

    async def test_message_contains_opportunity_id(self):
        notifier = self._make_notifier_with_mocked_send()
        cm, session = _patch_db()
        mock_row = MagicMock()
        mock_row.id = 77

        with patch("app.services.notifications.telegram_notifier.db_session", return_value=cm):
            with patch("app.services.notifications.telegram_notifier.Opportunity", return_value=mock_row):
                await notifier.send_opportunity_alert(_make_opportunity_dict())

        sent_text = notifier.send_message.call_args[0][0]
        assert "77" in sent_text
        assert "YES 77" in sent_text

    async def test_thesis_truncated_at_300_chars(self):
        long_thesis = "x" * 500
        notifier = self._make_notifier_with_mocked_send()
        cm, session = _patch_db()
        mock_row = MagicMock()
        mock_row.id = 1

        with patch("app.services.notifications.telegram_notifier.db_session", return_value=cm):
            with patch("app.services.notifications.telegram_notifier.Opportunity", return_value=mock_row):
                await notifier.send_opportunity_alert(_make_opportunity_dict(thesis=long_thesis))

        sent_text = notifier.send_message.call_args[0][0]
        assert "x" * 301 not in sent_text    # truncated

    async def test_returns_minus_one_on_db_error(self):
        notifier = self._make_notifier_with_mocked_send()

        with patch("app.services.notifications.telegram_notifier.db_session", side_effect=Exception("DB down")):
            opp_id = await notifier.send_opportunity_alert(_make_opportunity_dict())

        assert opp_id == -1
        notifier.send_message.assert_not_called()

    async def test_max_loss_calculated(self):
        notifier = self._make_notifier_with_mocked_send()
        cm, session = _patch_db()
        mock_row = MagicMock()
        mock_row.id = 5

        with patch("app.services.notifications.telegram_notifier.db_session", return_value=cm):
            with patch("app.services.notifications.telegram_notifier.Opportunity", return_value=mock_row):
                # $10k * 5% = $500 max loss
                await notifier.send_opportunity_alert(
                    _make_opportunity_dict(amount=10_000, stop_loss_pct=5.0)
                )

        sent = notifier.send_message.call_args[0][0]
        assert "$500" in sent


# ── TelegramNotifier.send_position_alert ──────────────────────────────────────

class TestSendPositionAlert:
    def _notifier(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            from app.services.notifications.telegram_notifier import TelegramNotifier
            n = TelegramNotifier()
        n.send_message = AsyncMock(return_value=True)
        return n

    async def test_warning_icon(self):
        n = self._notifier()
        await n.send_position_alert(
            {"ticker": "NVDA", "quantity": 10, "avg_entry_price": 100,
             "current_price": 90, "unrealized_pnl_pct": -10.0},
            "warning", "Price approaching support"
        )
        sent = n.send_message.call_args[0][0]
        assert "⚠️" in sent

    async def test_stop_loss_icon(self):
        n = self._notifier()
        await n.send_position_alert(
            {"ticker": "AMD", "quantity": 5, "avg_entry_price": 100,
             "current_price": 94, "unrealized_pnl_pct": -6.0},
            "stop_loss", "Stop triggered"
        )
        sent = n.send_message.call_args[0][0]
        assert "🛑" in sent

    async def test_profit_target_icon(self):
        n = self._notifier()
        await n.send_position_alert(
            {"ticker": "TSMC", "quantity": 3, "avg_entry_price": 100,
             "current_price": 120, "unrealized_pnl_pct": 20.0},
            "profit_target", "Target hit"
        )
        sent = n.send_message.call_args[0][0]
        assert "✅" in sent

    async def test_green_emoji_for_profit(self):
        n = self._notifier()
        await n.send_position_alert(
            {"ticker": "NVDA", "quantity": 10, "avg_entry_price": 100,
             "current_price": 110, "unrealized_pnl_pct": 10.0},
            "warning", ""
        )
        sent = n.send_message.call_args[0][0]
        assert "🟢" in sent

    async def test_red_emoji_for_loss(self):
        n = self._notifier()
        await n.send_position_alert(
            {"ticker": "NVDA", "quantity": 10, "avg_entry_price": 100,
             "current_price": 88, "unrealized_pnl_pct": -12.0},
            "warning", ""
        )
        sent = n.send_message.call_args[0][0]
        assert "🔴" in sent

    async def test_sell_and_hold_commands_present(self):
        n = self._notifier()
        await n.send_position_alert(
            {"ticker": "GLD", "quantity": 2, "avg_entry_price": 180,
             "current_price": 170, "unrealized_pnl_pct": -5.5},
            "warning", "analysis"
        )
        sent = n.send_message.call_args[0][0]
        assert "SELL GLD" in sent
        assert "HOLD GLD" in sent


# ── TelegramNotifier.send_execution_confirmation ──────────────────────────────

class TestSendExecutionConfirmation:
    def _notifier(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            from app.services.notifications.telegram_notifier import TelegramNotifier
            n = TelegramNotifier()
        n.send_message = AsyncMock(return_value=True)
        return n

    async def test_success_message_contains_checkmark(self):
        n = self._notifier()
        await n.send_execution_confirmation({
            "ticker": "NVDA", "action": "buy", "status": "filled",
            "quantity": 10, "filled_price": 123.45, "stop_loss": 117.28
        })
        sent = n.send_message.call_args[0][0]
        assert "✅" in sent
        assert "NVDA" in sent

    async def test_dry_run_noted(self):
        n = self._notifier()
        await n.send_execution_confirmation({
            "ticker": "AMD", "action": "buy", "status": "dry_run",
            "quantity": 5, "filled_price": None, "stop_loss": None
        })
        sent = n.send_message.call_args[0][0]
        assert "dry run" in sent.lower()

    async def test_failure_message_contains_x(self):
        n = self._notifier()
        await n.send_execution_confirmation({
            "ticker": "TSMC", "action": "buy", "status": "rejected",
            "error": "Account not authorized"
        })
        sent = n.send_message.call_args[0][0]
        assert "❌" in sent
        assert "Account not authorized" in sent

    async def test_filled_price_formatted(self):
        n = self._notifier()
        await n.send_execution_confirmation({
            "ticker": "NVDA", "action": "sell", "status": "filled",
            "quantity": 10, "filled_price": 450.75
        })
        sent = n.send_message.call_args[0][0]
        assert "450.75" in sent


# ── ApprovalHandler.handle_message routing ────────────────────────────────────

class TestHandleMessageRouting:
    def _make_handler(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            from app.services.notifications.telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier()
        notifier.send_message = AsyncMock(return_value=True)
        from app.services.notifications.approval_handler import ApprovalHandler
        handler = ApprovalHandler(notifier)
        return handler

    def _make_update(self, text: str):
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = text
        update.message.reply_text = AsyncMock()
        return update

    async def test_yes_routes_to_handle_approval(self):
        handler = self._make_handler()
        handler.handle_approval = AsyncMock()
        await handler.handle_message(self._make_update("YES 42"), MagicMock())
        handler.handle_approval.assert_awaited_once_with(42)

    async def test_no_routes_to_handle_rejection(self):
        handler = self._make_handler()
        handler.handle_rejection = AsyncMock()
        await handler.handle_message(self._make_update("NO 99"), MagicMock())
        handler.handle_rejection.assert_awaited_once_with(99)

    async def test_info_routes_to_handle_info(self):
        handler = self._make_handler()
        handler.handle_info_request = AsyncMock()
        await handler.handle_message(self._make_update("INFO 7"), MagicMock())
        handler.handle_info_request.assert_awaited_once_with(7)

    async def test_sell_routes_to_handle_sell(self):
        handler = self._make_handler()
        handler.handle_sell = AsyncMock()
        await handler.handle_message(self._make_update("SELL NVDA"), MagicMock())
        handler.handle_sell.assert_awaited_once_with("NVDA")

    async def test_status_routes_to_handle_status(self):
        handler = self._make_handler()
        handler.handle_status = AsyncMock()
        await handler.handle_message(self._make_update("STATUS"), MagicMock())
        handler.handle_status.assert_awaited_once()

    async def test_help_replies_with_help_text(self):
        handler = self._make_handler()
        update = self._make_update("HELP")
        await handler.handle_message(update, MagicMock())
        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0]
        assert "AVAILABLE COMMANDS" in args[0]

    async def test_hold_replies_with_holding_message(self):
        handler = self._make_handler()
        update = self._make_update("HOLD NVDA")
        await handler.handle_message(update, MagicMock())
        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "NVDA" in reply_text

    async def test_unknown_command_replies_with_hint(self):
        handler = self._make_handler()
        update = self._make_update("FOOBAR")
        await handler.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "HELP" in reply

    async def test_invalid_id_replies_gracefully(self):
        handler = self._make_handler()
        update = self._make_update("YES notanumber")
        await handler.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "Invalid ID" in reply

    async def test_case_insensitive_commands(self):
        """Lowercase 'yes' should also trigger handle_approval."""
        handler = self._make_handler()
        handler.handle_approval = AsyncMock()
        await handler.handle_message(self._make_update("yes 5"), MagicMock())
        handler.handle_approval.assert_awaited_once_with(5)


# ── ApprovalHandler.handle_approval ───────────────────────────────────────────

class TestHandleApproval:
    def _make_handler(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            from app.services.notifications.telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier()
        notifier.send_message = AsyncMock(return_value=True)
        notifier.send_execution_confirmation = AsyncMock()
        from app.services.notifications.approval_handler import ApprovalHandler
        handler = ApprovalHandler(notifier)
        return handler

    async def test_sends_not_found_for_missing_opportunity(self):
        handler = self._make_handler()
        cm, session = _patch_db(result=None)
        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            await handler.handle_approval(999)
        handler._notifier.send_message.assert_called_once()
        assert "not found" in handler._notifier.send_message.call_args[0][0].lower()

    async def test_sends_warning_for_non_pending_opportunity(self):
        handler = self._make_handler()
        opp = _make_opportunity_row(status="approved")
        cm, session = _patch_db(result=opp)
        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            await handler.handle_approval(42)
        sent = handler._notifier.send_message.call_args[0][0]
        assert "already" in sent.lower()

    async def test_rejects_when_validation_fails(self):
        from app.services.trading.position_manager import TradeValidationError

        handler = self._make_handler()
        opp = _make_opportunity_row(status="pending")
        cm, session = _patch_db(result=opp)

        mock_broker = MagicMock()
        mock_pm = MagicMock()
        mock_pm.validate_trade.side_effect = TradeValidationError("Max positions reached")
        handler._broker = mock_broker
        handler._pm = mock_pm

        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            with patch("app.services.notifications.approval_handler.Trade"):
                await handler.handle_approval(42)

        assert opp.status == "rejected"
        sent = handler._notifier.send_message.call_args[0][0]
        assert "validation failed" in sent.lower()

    async def test_executes_buy_and_logs_trade(self):
        handler = self._make_handler()
        opp = _make_opportunity_row(status="pending", confluence_score=0.8)
        cm, session = _patch_db(result=opp)

        mock_broker = MagicMock()
        mock_broker.execute_buy.return_value = MagicMock(
            filled_price=200.0, status="filled", order_id="ORD-1"
        )
        mock_pm = MagicMock()
        mock_pm.validate_trade.return_value = {
            "shares": 10.0, "estimated_cost": 2000.0,
            "stop_loss_pct": 0.05, "portfolio_pct": 0.15,
        }
        mock_pm.calculate_stop_loss.return_value = 190.0
        handler._broker = mock_broker
        handler._pm = mock_pm

        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            with patch("app.services.notifications.approval_handler.Trade") as MockTrade:
                await handler.handle_approval(42)

        mock_broker.execute_buy.assert_called_once_with("NVDA", 10.0, 0.05)
        MockTrade.log_execution.assert_called_once()
        assert opp.status == "approved"
        handler._notifier.send_execution_confirmation.assert_called_once()


# ── ApprovalHandler.handle_rejection ──────────────────────────────────────────

class TestHandleRejection:
    def _make_handler(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            from app.services.notifications.telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier()
        notifier.send_message = AsyncMock(return_value=True)
        from app.services.notifications.approval_handler import ApprovalHandler
        return ApprovalHandler(notifier)

    async def test_sets_status_to_rejected(self):
        handler = self._make_handler()
        opp = _make_opportunity_row(status="pending")
        cm, session = _patch_db(result=opp)
        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            await handler.handle_rejection(42)
        assert opp.status == "rejected"

    async def test_not_found_sends_message(self):
        handler = self._make_handler()
        cm, session = _patch_db(result=None)
        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            await handler.handle_rejection(999)
        handler._notifier.send_message.assert_called_once()
        assert "not found" in handler._notifier.send_message.call_args[0][0].lower()


# ── ApprovalHandler.handle_info_request ───────────────────────────────────────

class TestHandleInfoRequest:
    def _make_handler(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            from app.services.notifications.telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier()
        notifier.send_message = AsyncMock(return_value=True)
        from app.services.notifications.approval_handler import ApprovalHandler
        return ApprovalHandler(notifier)

    async def test_sends_full_thesis(self):
        handler = self._make_handler()
        opp = _make_opportunity_row(thesis="Complete thesis in full detail.")
        cm, session = _patch_db(result=opp)
        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            await handler.handle_info_request(42)
        sent = handler._notifier.send_message.call_args[0][0]
        assert "Complete thesis in full detail." in sent

    async def test_contains_ticker(self):
        handler = self._make_handler()
        opp = _make_opportunity_row(ticker="TSMC")
        cm, session = _patch_db(result=opp)
        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            await handler.handle_info_request(10)
        sent = handler._notifier.send_message.call_args[0][0]
        assert "TSMC" in sent

    async def test_not_found_sends_message(self):
        handler = self._make_handler()
        cm, session = _patch_db(result=None)
        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            await handler.handle_info_request(999)
        assert "not found" in handler._notifier.send_message.call_args[0][0].lower()


# ── ApprovalHandler.handle_sell ───────────────────────────────────────────────

class TestHandleSell:
    def _make_handler(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            from app.services.notifications.telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier()
        notifier.send_message = AsyncMock(return_value=True)
        notifier.send_execution_confirmation = AsyncMock()
        from app.services.notifications.approval_handler import ApprovalHandler
        return ApprovalHandler(notifier)

    async def test_sells_shares_and_sends_confirmation(self):
        handler = self._make_handler()
        pos = _make_position_row("NVDA", quantity=50.0)
        cm, session = _patch_db(result=pos)

        mock_broker = MagicMock()
        mock_broker.execute_sell.return_value = MagicMock(
            filled_price=450.0, status="filled", order_id="SELL-1"
        )
        handler._broker = mock_broker
        handler._pm = MagicMock()

        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            with patch("app.services.notifications.approval_handler.Trade") as MockTrade:
                await handler.handle_sell("NVDA")

        mock_broker.execute_sell.assert_called_once_with("NVDA", 50.0)
        MockTrade.log_execution.assert_called_once()
        session.delete.assert_called_once_with(pos)
        handler._notifier.send_execution_confirmation.assert_called_once()

    async def test_not_found_sends_message(self):
        handler = self._make_handler()
        cm, session = _patch_db(result=None)
        handler._broker = MagicMock()
        handler._pm = MagicMock()

        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            await handler.handle_sell("FAKE")

        sent = handler._notifier.send_message.call_args[0][0]
        assert "No open position" in sent

    async def test_zero_shares_sends_message(self):
        handler = self._make_handler()
        pos = _make_position_row("NVDA", quantity=0.0)
        cm, session = _patch_db(result=pos)
        handler._broker = MagicMock()
        handler._pm = MagicMock()

        with patch("app.services.notifications.approval_handler.db_session", return_value=cm):
            await handler.handle_sell("NVDA")

        sent = handler._notifier.send_message.call_args[0][0]
        assert "zero shares" in sent.lower()


# ── ApprovalHandler.handle_status ─────────────────────────────────────────────

class TestHandleStatus:
    def _make_handler(self):
        with patch("app.services.notifications.telegram_notifier.settings") as ms:
            ms.telegram_bot_token = "T"
            ms.telegram_chat_id = "C"
            from app.services.notifications.telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier()
        notifier.send_message = AsyncMock(return_value=True)
        from app.services.notifications.approval_handler import ApprovalHandler
        return ApprovalHandler(notifier)

    async def test_sends_portfolio_summary(self):
        from app.services.trading.broker_interface import AccountInfo, BrokerPosition

        handler = self._make_handler()
        mock_broker = MagicMock()
        mock_broker.get_account_info.return_value = AccountInfo(
            cash=50_000.0, portfolio_value=100_000.0, buying_power=50_000.0, is_paper=True
        )
        mock_broker.get_current_positions.return_value = [
            BrokerPosition(
                ticker="NVDA", quantity=10, avg_entry_price=400.0,
                current_price=440.0, market_value=4400.0,
                unrealized_pnl=400.0, unrealized_pnl_pct=10.0,
            )
        ]
        handler._broker = mock_broker
        handler._pm = MagicMock()

        await handler.handle_status()

        sent = handler._notifier.send_message.call_args[0][0]
        assert "PORTFOLIO STATUS" in sent
        assert "NVDA" in sent
        assert "100,000" in sent

    async def test_broker_error_sends_error_message(self):
        handler = self._make_handler()
        mock_broker = MagicMock()
        mock_broker.get_account_info.side_effect = Exception("Alpaca unreachable")
        handler._broker = mock_broker
        handler._pm = MagicMock()

        await handler.handle_status()

        sent = handler._notifier.send_message.call_args[0][0]
        assert "❌" in sent

    async def test_green_emoji_for_profitable_position(self):
        from app.services.trading.broker_interface import AccountInfo, BrokerPosition

        handler = self._make_handler()
        mock_broker = MagicMock()
        mock_broker.get_account_info.return_value = AccountInfo(
            cash=0, portfolio_value=100_000, buying_power=0
        )
        mock_broker.get_current_positions.return_value = [
            BrokerPosition(
                ticker="AMD", quantity=5, avg_entry_price=100.0,
                current_price=110.0, market_value=550.0,
                unrealized_pnl=50.0, unrealized_pnl_pct=10.0,
            )
        ]
        handler._broker = mock_broker
        handler._pm = MagicMock()

        await handler.handle_status()

        sent = handler._notifier.send_message.call_args[0][0]
        assert "🟢" in sent

    async def test_empty_positions(self):
        from app.services.trading.broker_interface import AccountInfo

        handler = self._make_handler()
        mock_broker = MagicMock()
        mock_broker.get_account_info.return_value = AccountInfo(
            cash=100_000, portfolio_value=100_000, buying_power=100_000
        )
        mock_broker.get_current_positions.return_value = []
        handler._broker = mock_broker
        handler._pm = MagicMock()

        await handler.handle_status()

        sent = handler._notifier.send_message.call_args[0][0]
        assert "No open positions" in sent


# ── ApprovalHandler._score_to_conviction ──────────────────────────────────────

class TestScoreToConviction:
    def test_high_conviction(self):
        from app.services.notifications.approval_handler import ApprovalHandler
        assert ApprovalHandler._score_to_conviction(0.70) == "high"
        assert ApprovalHandler._score_to_conviction(0.99) == "high"

    def test_medium_conviction(self):
        from app.services.notifications.approval_handler import ApprovalHandler
        assert ApprovalHandler._score_to_conviction(0.50) == "medium"
        assert ApprovalHandler._score_to_conviction(0.69) == "medium"

    def test_low_conviction(self):
        from app.services.notifications.approval_handler import ApprovalHandler
        assert ApprovalHandler._score_to_conviction(0.0) == "low"
        assert ApprovalHandler._score_to_conviction(0.49) == "low"
