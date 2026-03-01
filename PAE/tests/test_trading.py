"""Tests for trading services and Trade model helpers."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.services.trading.broker_interface import (
    AccountInfo,
    BrokerError,
    BrokerPosition,
    InsufficientFundsError,
    OrderRejectedError,
    OrderResult,
)
from app.services.trading.position_manager import (
    PositionManager,
    TradeValidationError,
    _CONVICTION_SIZE,
    _MAX_POSITIONS,
    _MAX_EXPOSURE_RATIO,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _account(
    cash: float = 100_000,
    portfolio_value: float = 100_000,
    buying_power: float = 100_000,
) -> AccountInfo:
    return AccountInfo(
        cash=cash,
        portfolio_value=portfolio_value,
        buying_power=buying_power,
        is_paper=True,
    )


def _position(ticker: str = "NVDA", quantity: float = 10, market_value: float = 5_000) -> BrokerPosition:
    return BrokerPosition(
        ticker=ticker,
        quantity=quantity,
        avg_entry_price=market_value / quantity,
        current_price=market_value / quantity,
        market_value=market_value,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
    )


def _make_broker(
    positions: list[BrokerPosition] | None = None,
    account: AccountInfo | None = None,
    price: float = 100.0,
) -> MagicMock:
    broker = MagicMock()
    broker.get_current_positions.return_value = positions or []
    broker.get_account_info.return_value = account or _account()
    broker.get_current_price.return_value = price
    return broker


def _make_order(
    ticker: str = "NVDA",
    action: str = "buy",
    quantity: float = 10,
    filled_price: float = 100.0,
    status: str = "filled",
) -> OrderResult:
    return OrderResult(
        order_id="abc123",
        ticker=ticker,
        action=action,
        quantity=quantity,
        filled_price=filled_price,
        status=status,
    )


def _make_db(trades: list = None) -> MagicMock:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.all.return_value = trades or []
    q.first.return_value = None
    db.query.return_value = q
    db.add = MagicMock()
    db.flush = MagicMock()
    return db


# ── Trade.log_execution ────────────────────────────────────────────────────────

class TestTradeLogExecution:
    def test_creates_buy_row(self):
        from app.models.trade import Trade

        db = _make_db()
        with patch.object(Trade, "__init__", lambda self, **kw: None):
            with patch("app.models.trade.Trade") as MockTrade:
                mock_row = MagicMock()
                mock_row.id = 1
                MockTrade.return_value = mock_row

                result = Trade.log_execution(
                    db,
                    ticker="NVDA",
                    action="buy",
                    quantity=5,
                    price=200.0,
                )

        db.add.assert_called_once()
        db.flush.assert_called_once()

    def test_buy_sets_entry_price(self):
        from app.models.trade import Trade

        db = _make_db()
        with patch("app.models.trade.Trade") as MockTrade:
            mock_row = MagicMock()
            mock_row.id = 2
            MockTrade.return_value = mock_row
            Trade.log_execution(db, ticker="AMD", action="buy", quantity=10, price=150.0)

        _, kwargs = MockTrade.call_args
        assert kwargs["entry_price"] == 150.0
        assert kwargs["exit_price"] is None

    def test_sell_sets_exit_price(self):
        from app.models.trade import Trade

        db = _make_db()
        with patch("app.models.trade.Trade") as MockTrade:
            mock_row = MagicMock()
            mock_row.id = 3
            MockTrade.return_value = mock_row
            Trade.log_execution(db, ticker="AMD", action="sell", quantity=10, price=175.0)

        _, kwargs = MockTrade.call_args
        assert kwargs["exit_price"] == 175.0
        assert kwargs["entry_price"] is None

    def test_action_normalised_to_lowercase(self):
        from app.models.trade import Trade

        db = _make_db()
        with patch("app.models.trade.Trade") as MockTrade:
            mock_row = MagicMock()
            mock_row.id = 4
            MockTrade.return_value = mock_row
            Trade.log_execution(db, ticker="TSMC", action="BUY", quantity=1, price=100.0)

        _, kwargs = MockTrade.call_args
        assert kwargs["action"] == "buy"

    def test_approved_is_true(self):
        from app.models.trade import Trade

        db = _make_db()
        with patch("app.models.trade.Trade") as MockTrade:
            mock_row = MagicMock()
            mock_row.id = 5
            MockTrade.return_value = mock_row
            Trade.log_execution(db, ticker="INTC", action="buy", quantity=2, price=30.0)

        _, kwargs = MockTrade.call_args
        assert kwargs["approved"] is True

    def test_optional_fields_passed_through(self):
        from app.models.trade import Trade

        db = _make_db()
        with patch("app.models.trade.Trade") as MockTrade:
            mock_row = MagicMock()
            mock_row.id = 6
            MockTrade.return_value = mock_row
            Trade.log_execution(
                db,
                ticker="GLD",
                action="buy",
                quantity=3,
                price=180.0,
                stop_loss=170.0,
                opportunity_id=42,
                strategy_id=1,
                notes="order_id=XYZ",
            )

        _, kwargs = MockTrade.call_args
        assert kwargs["stop_loss"] == 170.0
        assert kwargs["opportunity_id"] == 42
        assert kwargs["strategy_id"] == 1
        assert kwargs["notes"] == "order_id=XYZ"


# ── Trade.get_active_trades ────────────────────────────────────────────────────

class TestGetActiveTrades:
    def test_returns_open_buys(self):
        from app.models.trade import Trade

        mock_trade = MagicMock()
        mock_trade.action = "buy"
        mock_trade.exit_price = None
        mock_trade.closed_at = None

        db = _make_db(trades=[mock_trade])
        result = Trade.get_active_trades(db)
        assert len(result) == 1

    def test_empty_when_no_trades(self):
        from app.models.trade import Trade

        db = _make_db(trades=[])
        result = Trade.get_active_trades(db)
        assert result == []

    def test_query_filters_applied(self):
        from app.models.trade import Trade

        db = _make_db()
        Trade.get_active_trades(db)
        db.query.assert_called_once_with(Trade)


# ── Trade.calculate_returns ────────────────────────────────────────────────────

class TestCalculateReturns:
    def _closed_trade(self, return_pct: float) -> MagicMock:
        t = MagicMock()
        t.return_pct = return_pct
        t.closed_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        return t

    def test_empty_returns_zero_totals(self):
        from app.models.trade import Trade

        db = _make_db(trades=[])
        result = Trade.calculate_returns(db)
        assert result["total_trades"] == 0
        assert result["win_rate"] is None
        assert result["avg_return_pct"] is None

    def test_all_winning(self):
        from app.models.trade import Trade

        trades = [self._closed_trade(5.0), self._closed_trade(3.0), self._closed_trade(10.0)]
        db = _make_db(trades=trades)
        result = Trade.calculate_returns(db)
        assert result["total_trades"] == 3
        assert result["winning_trades"] == 3
        assert result["losing_trades"] == 0
        assert result["win_rate"] == 1.0

    def test_mixed_wins_losses(self):
        from app.models.trade import Trade

        trades = [
            self._closed_trade(10.0),
            self._closed_trade(-5.0),
            self._closed_trade(2.0),
        ]
        db = _make_db(trades=trades)
        result = Trade.calculate_returns(db)
        assert result["winning_trades"] == 2
        assert result["losing_trades"] == 1
        assert abs(result["win_rate"] - 2 / 3) < 1e-6

    def test_avg_return_calculated(self):
        from app.models.trade import Trade

        trades = [self._closed_trade(10.0), self._closed_trade(-10.0)]
        db = _make_db(trades=trades)
        result = Trade.calculate_returns(db)
        assert result["avg_return_pct"] == 0.0
        assert result["total_return_pct"] == 0.0

    def test_total_return_summed(self):
        from app.models.trade import Trade

        trades = [self._closed_trade(5.0), self._closed_trade(7.0), self._closed_trade(-2.0)]
        db = _make_db(trades=trades)
        result = Trade.calculate_returns(db)
        assert abs(result["total_return_pct"] - 10.0) < 1e-9


# ── PositionManager.can_add_position ──────────────────────────────────────────

class TestCanAddPosition:
    def test_allowed_when_empty(self):
        pm = PositionManager(_make_broker())
        allowed, reason = pm.can_add_position()
        assert allowed is True
        assert reason == ""

    def test_blocked_at_max_positions(self):
        positions = [_position(f"TICK{i}", market_value=1_000) for i in range(_MAX_POSITIONS)]
        broker = _make_broker(positions=positions)
        pm = PositionManager(broker)
        allowed, reason = pm.can_add_position()
        assert allowed is False
        assert "Max position limit" in reason

    def test_blocked_at_max_exposure(self):
        # 91% exposure
        positions = [_position("NVDA", market_value=91_000)]
        broker = _make_broker(
            positions=positions,
            account=_account(portfolio_value=100_000),
        )
        pm = PositionManager(broker)
        allowed, reason = pm.can_add_position()
        assert allowed is False
        assert "Exposure limit" in reason

    def test_allowed_just_below_exposure_limit(self):
        positions = [_position("NVDA", market_value=89_000)]
        broker = _make_broker(
            positions=positions,
            account=_account(portfolio_value=100_000),
        )
        pm = PositionManager(broker)
        allowed, _ = pm.can_add_position()
        assert allowed is True

    def test_broker_error_returns_false(self):
        broker = _make_broker()
        broker.get_current_positions.side_effect = BrokerError("network error")
        pm = PositionManager(broker)
        allowed, reason = pm.can_add_position()
        assert allowed is False
        assert "Broker query failed" in reason


# ── PositionManager.calculate_shares ──────────────────────────────────────────

class TestCalculateShares:
    def test_low_conviction_is_5_pct(self):
        broker = _make_broker(account=_account(portfolio_value=100_000), price=100.0)
        pm = PositionManager(broker)
        shares = pm.calculate_shares("NVDA", "low")
        # 5% of 100k = $5000, at $100/share = 50 shares
        assert shares == 50.0

    def test_medium_conviction_is_10_pct(self):
        broker = _make_broker(account=_account(portfolio_value=100_000), price=100.0)
        pm = PositionManager(broker)
        shares = pm.calculate_shares("NVDA", "medium")
        assert shares == 100.0

    def test_high_conviction_is_15_pct(self):
        broker = _make_broker(account=_account(portfolio_value=100_000), price=100.0)
        pm = PositionManager(broker)
        shares = pm.calculate_shares("NVDA", "high")
        assert shares == 150.0

    def test_floors_to_whole_share(self):
        # price=$333, 5% of $100k = $5000, 5000/333 = 15.01... → floor to 15
        broker = _make_broker(account=_account(portfolio_value=100_000), price=333.0)
        pm = PositionManager(broker)
        shares = pm.calculate_shares("GOOG", "low")
        assert shares == math.floor(5_000 / 333)

    def test_raises_for_unknown_conviction(self):
        pm = PositionManager(_make_broker())
        with pytest.raises(TradeValidationError, match="Unknown conviction"):
            pm.calculate_shares("NVDA", "ultra")  # type: ignore[arg-type]

    def test_raises_when_broker_errors(self):
        broker = _make_broker()
        broker.get_account_info.side_effect = BrokerError("timeout")
        pm = PositionManager(broker)
        with pytest.raises(TradeValidationError, match="broker error"):
            pm.calculate_shares("NVDA", "low")

    def test_zero_price_raises(self):
        broker = _make_broker(price=0.0)
        pm = PositionManager(broker)
        with pytest.raises(TradeValidationError, match="Invalid price"):
            pm.calculate_shares("NVDA", "low")


# ── PositionManager.calculate_stop_loss ───────────────────────────────────────

class TestCalculateStopLoss:
    def setup_method(self):
        self.pm = PositionManager(_make_broker())

    def test_5pct_stop(self):
        result = self.pm.calculate_stop_loss(100.0, 0.05)
        assert abs(result - 95.0) < 0.01

    def test_10pct_stop(self):
        result = self.pm.calculate_stop_loss(200.0, 0.10)
        assert abs(result - 180.0) < 0.01

    def test_rounded_to_2dp(self):
        # 150 * (1 - 0.07) = 139.5  (exact)
        result = self.pm.calculate_stop_loss(150.0, 0.07)
        assert result == 139.5

    def test_raises_below_min(self):
        with pytest.raises(TradeValidationError, match="outside the allowed range"):
            self.pm.calculate_stop_loss(100.0, 0.005)   # 0.5% < 1% min

    def test_raises_above_max(self):
        with pytest.raises(TradeValidationError, match="outside the allowed range"):
            self.pm.calculate_stop_loss(100.0, 0.30)    # 30% > 25% max

    def test_boundary_values_accepted(self):
        # 1% and 25% are both valid
        self.pm.calculate_stop_loss(100.0, 0.01)
        self.pm.calculate_stop_loss(100.0, 0.25)


# ── PositionManager.validate_trade ────────────────────────────────────────────

class TestValidateTrade:
    def test_returns_sizing_summary(self):
        broker = _make_broker(account=_account(portfolio_value=100_000, buying_power=100_000), price=100.0)
        pm = PositionManager(broker)
        result = pm.validate_trade("NVDA", "medium", stop_loss_pct=0.05)
        assert result["ticker"] == "NVDA"
        assert result["shares"] == 100.0
        assert result["stop_loss_pct"] == 0.05
        assert result["portfolio_pct"] == 0.10

    def test_raises_when_position_limit_hit(self):
        positions = [_position(f"T{i}", market_value=1_000) for i in range(_MAX_POSITIONS)]
        broker = _make_broker(positions=positions)
        pm = PositionManager(broker)
        with pytest.raises(TradeValidationError, match="Max position limit"):
            pm.validate_trade("NVDA", "low")

    def test_raises_when_shares_round_to_zero(self):
        # price = $2_000_000, portfolio = $100k, 5% = $5k → 0 shares
        broker = _make_broker(
            account=_account(portfolio_value=100_000, buying_power=100_000),
            price=2_000_000.0,
        )
        pm = PositionManager(broker)
        with pytest.raises(TradeValidationError, match="0 shares"):
            pm.validate_trade("BRK.A", "low")

    def test_raises_on_insufficient_funds(self):
        # 10 shares * $100 = $1000, but buying_power = $500
        broker = _make_broker(
            account=_account(portfolio_value=10_000, buying_power=500),
            price=100.0,
        )
        pm = PositionManager(broker)
        with pytest.raises(TradeValidationError, match="Insufficient buying power"):
            pm.validate_trade("NVDA", "low")

    def test_raises_on_bad_stop_loss(self):
        broker = _make_broker()
        pm = PositionManager(broker)
        with pytest.raises(TradeValidationError, match="outside the allowed range"):
            pm.validate_trade("NVDA", "low", stop_loss_pct=0.50)

    def test_estimated_cost_correct(self):
        broker = _make_broker(
            account=_account(portfolio_value=100_000, buying_power=100_000),
            price=50.0,
        )
        pm = PositionManager(broker)
        result = pm.validate_trade("AMD", "low")
        # 5% of 100k = $5000, at $50 = 100 shares, cost = 100 * 50 = $5000
        assert result["estimated_cost"] == 5_000.0


# ── PositionManager.get_position_summary ──────────────────────────────────────

class TestGetPositionSummary:
    def test_empty_portfolio(self):
        broker = _make_broker()
        pm = PositionManager(broker)
        summary = pm.get_position_summary()
        assert summary["position_count"] == 0
        assert summary["can_trade"] is True
        assert summary["exposure_ratio"] == 0.0
        assert summary["available_slots"] == _MAX_POSITIONS

    def test_counts_positions(self):
        positions = [_position("NVDA", market_value=5_000), _position("AMD", market_value=5_000)]
        broker = _make_broker(positions=positions, account=_account(portfolio_value=100_000))
        pm = PositionManager(broker)
        summary = pm.get_position_summary()
        assert summary["position_count"] == 2
        assert summary["available_slots"] == _MAX_POSITIONS - 2

    def test_exposure_ratio_computed(self):
        positions = [_position("NVDA", market_value=40_000)]
        broker = _make_broker(positions=positions, account=_account(portfolio_value=100_000))
        pm = PositionManager(broker)
        summary = pm.get_position_summary()
        assert abs(summary["exposure_ratio"] - 0.40) < 1e-6

    def test_can_trade_false_at_limit(self):
        positions = [_position(f"T{i}", market_value=1_000) for i in range(_MAX_POSITIONS)]
        broker = _make_broker(positions=positions)
        pm = PositionManager(broker)
        summary = pm.get_position_summary()
        assert summary["can_trade"] is False

    def test_broker_error_returns_empty_dict(self):
        broker = _make_broker()
        broker.get_current_positions.side_effect = Exception("timeout")
        pm = PositionManager(broker)
        summary = pm.get_position_summary()
        assert summary == {}


# ── AlpacaBroker — unit tests (all broker calls mocked) ───────────────────────

class TestAlpacaBrokerDryRun:
    """All tests run with dry_run=True so no real network calls are made."""

    def _make_alpaca_broker(self):
        """Create an AlpacaBroker with mocked alpaca-py clients."""
        with patch("app.services.trading.alpaca_interface.settings") as mock_settings:
            mock_settings.alpaca_api_key = "TEST_KEY"
            mock_settings.alpaca_secret_key = "TEST_SECRET"
            mock_settings.paper_trading = True
            mock_settings.dry_run = True

            with patch("app.services.trading.alpaca_interface.TradingClient", create=True) as MockTC:
                with patch("app.services.trading.alpaca_interface.StockHistoricalDataClient", create=True):
                    # Import after patching
                    from app.services.trading.alpaca_interface import AlpacaBroker

                    # Patch the imports inside __init__
                    with patch.dict("sys.modules", {
                        "alpaca": MagicMock(),
                        "alpaca.trading": MagicMock(),
                        "alpaca.trading.client": MagicMock(),
                        "alpaca.data": MagicMock(),
                        "alpaca.data.historical": MagicMock(),
                    }):
                        broker = MagicMock(spec=AlpacaBroker)
                        broker._dry_run = True
                        broker._trading = MagicMock()
                        broker._data = MagicMock()
                        return broker

    def test_execute_buy_dry_run_returns_dry_run_status(self):
        from app.services.trading.alpaca_interface import AlpacaBroker

        # Directly test the dry_run branch by patching settings
        with patch("app.services.trading.alpaca_interface.settings") as mock_settings:
            mock_settings.alpaca_api_key = "K"
            mock_settings.alpaca_secret_key = "S"
            mock_settings.paper_trading = True
            mock_settings.dry_run = True

            with patch.dict("sys.modules", {
                "alpaca": MagicMock(),
                "alpaca.trading": MagicMock(),
                "alpaca.trading.client": MagicMock(TradingClient=MagicMock()),
                "alpaca.data": MagicMock(),
                "alpaca.data.historical": MagicMock(StockHistoricalDataClient=MagicMock()),
                "alpaca.trading.requests": MagicMock(),
                "alpaca.trading.enums": MagicMock(),
                "alpaca.data.requests": MagicMock(),
            }):
                broker = AlpacaBroker()
                result = broker.execute_buy("NVDA", 10.0, stop_loss_pct=0.05)

        assert result.status == "dry_run"
        assert result.ticker == "NVDA"
        assert result.action == "buy"

    def test_execute_sell_dry_run_returns_dry_run_status(self):
        from app.services.trading.alpaca_interface import AlpacaBroker

        with patch("app.services.trading.alpaca_interface.settings") as mock_settings:
            mock_settings.alpaca_api_key = "K"
            mock_settings.alpaca_secret_key = "S"
            mock_settings.paper_trading = True
            mock_settings.dry_run = True

            with patch.dict("sys.modules", {
                "alpaca": MagicMock(),
                "alpaca.trading": MagicMock(),
                "alpaca.trading.client": MagicMock(TradingClient=MagicMock()),
                "alpaca.data": MagicMock(),
                "alpaca.data.historical": MagicMock(StockHistoricalDataClient=MagicMock()),
                "alpaca.trading.requests": MagicMock(),
                "alpaca.trading.enums": MagicMock(),
                "alpaca.data.requests": MagicMock(),
            }):
                broker = AlpacaBroker()
                result = broker.execute_sell("NVDA", 5.0)

        assert result.status == "dry_run"
        assert result.action == "sell"

    def test_cancel_order_dry_run_returns_true(self):
        from app.services.trading.alpaca_interface import AlpacaBroker

        with patch("app.services.trading.alpaca_interface.settings") as mock_settings:
            mock_settings.alpaca_api_key = "K"
            mock_settings.alpaca_secret_key = "S"
            mock_settings.paper_trading = True
            mock_settings.dry_run = True

            with patch.dict("sys.modules", {
                "alpaca": MagicMock(),
                "alpaca.trading": MagicMock(),
                "alpaca.trading.client": MagicMock(TradingClient=MagicMock()),
                "alpaca.data": MagicMock(),
                "alpaca.data.historical": MagicMock(StockHistoricalDataClient=MagicMock()),
                "alpaca.trading.requests": MagicMock(),
                "alpaca.trading.enums": MagicMock(),
                "alpaca.data.requests": MagicMock(),
            }):
                broker = AlpacaBroker()
                assert broker.cancel_order("some-order-id") is True


# ── AlpacaBroker._poll_fill ────────────────────────────────────────────────────

class TestAlpacaPollFill:
    """Test _poll_fill directly with mocked trading client."""

    def _broker_with_mock_trading(self, order_statuses: list[str], filled_price: float = 123.45):
        """Build an AlpacaBroker with a mock _trading client."""
        from app.services.trading.alpaca_interface import AlpacaBroker

        with patch("app.services.trading.alpaca_interface.settings") as mock_settings:
            mock_settings.alpaca_api_key = "K"
            mock_settings.alpaca_secret_key = "S"
            mock_settings.paper_trading = True
            mock_settings.dry_run = False

            with patch.dict("sys.modules", {
                "alpaca": MagicMock(),
                "alpaca.trading": MagicMock(),
                "alpaca.trading.client": MagicMock(TradingClient=MagicMock()),
                "alpaca.data": MagicMock(),
                "alpaca.data.historical": MagicMock(StockHistoricalDataClient=MagicMock()),
            }):
                broker = AlpacaBroker()

        # Build sequence of order mock responses
        responses = []
        for i, status in enumerate(order_statuses):
            o = MagicMock()
            o.status = status
            o.filled_avg_price = filled_price if status == "filled" else None
            responses.append(o)

        broker._trading = MagicMock()
        broker._trading.get_order_by_id.side_effect = responses
        return broker

    def test_returns_price_on_immediate_fill(self):
        with patch("app.services.trading.alpaca_interface.settings") as mock_settings:
            mock_settings.alpaca_api_key = "K"
            mock_settings.alpaca_secret_key = "S"
            mock_settings.paper_trading = True
            mock_settings.dry_run = False

            with patch.dict("sys.modules", {
                "alpaca": MagicMock(),
                "alpaca.trading": MagicMock(),
                "alpaca.trading.client": MagicMock(TradingClient=MagicMock()),
                "alpaca.data": MagicMock(),
                "alpaca.data.historical": MagicMock(StockHistoricalDataClient=MagicMock()),
            }):
                from app.services.trading.alpaca_interface import AlpacaBroker
                broker = AlpacaBroker()

        order = MagicMock()
        order.status = "filled"
        order.filled_avg_price = 99.99
        broker._trading = MagicMock()
        broker._trading.get_order_by_id.return_value = order

        with patch("app.services.trading.alpaca_interface.time.sleep"):
            price = broker._poll_fill("order-1")

        assert abs(price - 99.99) < 1e-6

    def test_returns_none_on_cancelled(self):
        with patch("app.services.trading.alpaca_interface.settings") as mock_settings:
            mock_settings.alpaca_api_key = "K"
            mock_settings.alpaca_secret_key = "S"
            mock_settings.paper_trading = True
            mock_settings.dry_run = False

            with patch.dict("sys.modules", {
                "alpaca": MagicMock(),
                "alpaca.trading": MagicMock(),
                "alpaca.trading.client": MagicMock(TradingClient=MagicMock()),
                "alpaca.data": MagicMock(),
                "alpaca.data.historical": MagicMock(StockHistoricalDataClient=MagicMock()),
            }):
                from app.services.trading.alpaca_interface import AlpacaBroker
                broker = AlpacaBroker()

        order = MagicMock()
        order.status = "cancelled"
        order.filled_avg_price = None
        broker._trading = MagicMock()
        broker._trading.get_order_by_id.return_value = order

        with patch("app.services.trading.alpaca_interface.time.sleep"):
            price = broker._poll_fill("order-2")

        assert price is None

    def test_returns_none_after_max_attempts(self):
        with patch("app.services.trading.alpaca_interface.settings") as mock_settings:
            mock_settings.alpaca_api_key = "K"
            mock_settings.alpaca_secret_key = "S"
            mock_settings.paper_trading = True
            mock_settings.dry_run = False

            with patch.dict("sys.modules", {
                "alpaca": MagicMock(),
                "alpaca.trading": MagicMock(),
                "alpaca.trading.client": MagicMock(TradingClient=MagicMock()),
                "alpaca.data": MagicMock(),
                "alpaca.data.historical": MagicMock(StockHistoricalDataClient=MagicMock()),
            }):
                from app.services.trading.alpaca_interface import AlpacaBroker
                broker = AlpacaBroker()

        order = MagicMock()
        order.status = "pending_new"
        order.filled_avg_price = None
        broker._trading = MagicMock()
        broker._trading.get_order_by_id.return_value = order

        with patch("app.services.trading.alpaca_interface.time.sleep"):
            with patch("app.services.trading.alpaca_interface._POLL_MAX_ATTEMPTS", 3):
                price = broker._poll_fill("order-3")

        assert price is None


# ── BrokerInterface value objects ─────────────────────────────────────────────

class TestValueObjects:
    def test_account_info_defaults(self):
        acct = AccountInfo(cash=1000, portfolio_value=1000, buying_power=1000)
        assert acct.currency == "USD"
        assert acct.is_paper is True
        assert acct.raw == {}

    def test_broker_position_fields(self):
        pos = BrokerPosition(
            ticker="NVDA",
            quantity=10,
            avg_entry_price=100.0,
            current_price=120.0,
            market_value=1200.0,
            unrealized_pnl=200.0,
            unrealized_pnl_pct=20.0,
        )
        assert pos.ticker == "NVDA"
        assert pos.raw == {}

    def test_order_result_fields(self):
        order = OrderResult(
            order_id="xyz",
            ticker="AMD",
            action="buy",
            quantity=5,
            filled_price=150.0,
            status="filled",
        )
        assert order.filled_price == 150.0
        assert order.raw == {}
