"""Alpaca Markets broker implementation using alpaca-py SDK.

Uses:
- ``alpaca.trading.client.TradingClient``        — orders, positions, account
- ``alpaca.data.historical.StockHistoricalDataClient`` — latest quote/trade

DRY_RUN mode (``settings.dry_run = True``) logs every intended action but
never submits an order.  All ``execute_*`` methods return a synthetic
:class:`~broker_interface.OrderResult` with ``status="dry_run"`` so callers
can proceed with logging without special-casing.
"""

from __future__ import annotations

import logging
import time

from app.core.config import settings
from app.services.trading.broker_interface import (
    AccountInfo,
    BrokerError,
    BrokerInterface,
    BrokerPosition,
    InsufficientFundsError,
    OrderRejectedError,
    OrderResult,
)

logger = logging.getLogger(__name__)

# Fill-poll configuration
_POLL_INTERVAL_S = 1.0
_POLL_MAX_ATTEMPTS = 10


class AlpacaBroker(BrokerInterface):
    """Alpaca Markets adapter (paper or live, based on ``settings.paper_trading``)."""

    def __init__(self) -> None:
        # Deferred import so the module can be imported even without alpaca-py
        # installed (e.g. in unit-test environments that mock the client).
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical import StockHistoricalDataClient
        except ImportError as exc:  # pragma: no cover
            raise BrokerError(
                "alpaca-py is not installed. Run: pip install alpaca-py"
            ) from exc

        self._trading = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=settings.paper_trading,
        )
        self._data = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        self._dry_run = settings.dry_run
        logger.info(
            "AlpacaBroker initialised (paper=%s, dry_run=%s)",
            settings.paper_trading,
            self._dry_run,
        )

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_info(self) -> AccountInfo:
        try:
            acct = self._trading.get_account()
        except Exception as exc:
            raise BrokerError(f"get_account failed: {exc}") from exc

        return AccountInfo(
            cash=float(acct.cash),
            portfolio_value=float(acct.portfolio_value),
            buying_power=float(acct.buying_power),
            currency=acct.currency or "USD",
            account_number=acct.account_number or "",
            is_paper=settings.paper_trading,
            raw=acct.model_dump() if hasattr(acct, "model_dump") else {},
        )

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_current_positions(self) -> list[BrokerPosition]:
        try:
            positions = self._trading.get_all_positions()
        except Exception as exc:
            raise BrokerError(f"get_all_positions failed: {exc}") from exc

        return [
            BrokerPosition(
                ticker=p.symbol,
                quantity=float(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pnl=float(p.unrealized_pl),
                unrealized_pnl_pct=float(p.unrealized_plpc) * 100,
                raw=p.model_dump() if hasattr(p, "model_dump") else {},
            )
            for p in positions
        ]

    # ── Market data ───────────────────────────────────────────────────────────

    def get_current_price(self, ticker: str) -> float:
        try:
            from alpaca.data.requests import StockLatestTradeRequest

            req = StockLatestTradeRequest(symbol_or_symbols=ticker)
            trades = self._data.get_stock_latest_trade(req)
            price = float(trades[ticker].price)
            logger.debug("get_current_price(%s) = %.4f", ticker, price)
            return price
        except Exception as exc:
            raise BrokerError(f"get_current_price({ticker!r}) failed: {exc}") from exc

    # ── Order execution ───────────────────────────────────────────────────────

    def execute_buy(
        self,
        ticker: str,
        shares: float,
        stop_loss_pct: float | None = None,
    ) -> OrderResult:
        """Submit a market buy order, optionally attach a stop-loss."""
        if self._dry_run:
            logger.info(
                "[DRY_RUN] execute_buy %s x %.4f (stop_loss_pct=%s)",
                ticker, shares, stop_loss_pct,
            )
            return OrderResult(
                order_id="dry-run",
                ticker=ticker,
                action="buy",
                quantity=shares,
                filled_price=None,
                status="dry_run",
            )

        from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        # Check buying power
        try:
            acct = self._trading.get_account()
            required = shares * self.get_current_price(ticker)
            if float(acct.buying_power) < required:
                raise InsufficientFundsError(
                    f"Need ${required:.2f} but buying_power=${float(acct.buying_power):.2f}"
                )
        except InsufficientFundsError:
            raise
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"Pre-order account check failed: {exc}") from exc

        # Submit market order
        try:
            req = MarketOrderRequest(
                symbol=ticker,
                qty=shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            order = self._trading.submit_order(req)
        except Exception as exc:
            raise OrderRejectedError(f"Buy order rejected for {ticker}: {exc}") from exc

        logger.info("Buy order submitted: %s id=%s", ticker, order.id)

        # Poll for fill
        filled_price = self._poll_fill(str(order.id))

        # Attach stop-loss if requested and we have a fill price
        if stop_loss_pct is not None and filled_price is not None:
            stop_price = round(filled_price * (1.0 - stop_loss_pct), 2)
            try:
                stop_req = StopOrderRequest(
                    symbol=ticker,
                    qty=shares,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC,
                    stop_price=stop_price,
                )
                self._trading.submit_order(stop_req)
                logger.info(
                    "Stop-loss order placed: %s @ %.2f (%.1f%% below fill)",
                    ticker, stop_price, stop_loss_pct * 100,
                )
            except Exception as exc:
                # Stop-loss failure is non-fatal — log and continue
                logger.warning("Failed to place stop-loss for %s: %s", ticker, exc)

        return OrderResult(
            order_id=str(order.id),
            ticker=ticker,
            action="buy",
            quantity=shares,
            filled_price=filled_price,
            status="filled" if filled_price is not None else "pending",
            raw=order.model_dump() if hasattr(order, "model_dump") else {},
        )

    def execute_sell(self, ticker: str, shares: float) -> OrderResult:
        """Submit a market sell order."""
        if self._dry_run:
            logger.info("[DRY_RUN] execute_sell %s x %.4f", ticker, shares)
            return OrderResult(
                order_id="dry-run",
                ticker=ticker,
                action="sell",
                quantity=shares,
                filled_price=None,
                status="dry_run",
            )

        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        try:
            req = MarketOrderRequest(
                symbol=ticker,
                qty=shares,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = self._trading.submit_order(req)
        except Exception as exc:
            raise OrderRejectedError(f"Sell order rejected for {ticker}: {exc}") from exc

        logger.info("Sell order submitted: %s id=%s", ticker, order.id)
        filled_price = self._poll_fill(str(order.id))

        return OrderResult(
            order_id=str(order.id),
            ticker=ticker,
            action="sell",
            quantity=shares,
            filled_price=filled_price,
            status="filled" if filled_price is not None else "pending",
            raw=order.model_dump() if hasattr(order, "model_dump") else {},
        )

    def cancel_order(self, order_id: str) -> bool:
        if self._dry_run:
            logger.info("[DRY_RUN] cancel_order %s", order_id)
            return True

        try:
            self._trading.cancel_order_by_id(order_id)
            return True
        except Exception as exc:
            logger.warning("cancel_order(%s) failed: %s", order_id, exc)
            return False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _poll_fill(self, order_id: str) -> float | None:
        """Poll until the order fills or ``_POLL_MAX_ATTEMPTS`` is exhausted.

        Returns the average fill price, or ``None`` if still pending.
        """
        for attempt in range(_POLL_MAX_ATTEMPTS):
            try:
                order = self._trading.get_order_by_id(order_id)
                status = str(order.status).lower()
                if status == "filled" and order.filled_avg_price is not None:
                    price = float(order.filled_avg_price)
                    logger.info(
                        "Order %s filled @ %.4f (poll attempt %d)",
                        order_id, price, attempt + 1,
                    )
                    return price
                if status in {"cancelled", "expired", "rejected"}:
                    logger.warning("Order %s ended with status=%s", order_id, status)
                    return None
            except Exception as exc:
                logger.warning(
                    "Poll attempt %d for order %s failed: %s",
                    attempt + 1, order_id, exc,
                )
            time.sleep(_POLL_INTERVAL_S)

        logger.warning(
            "Order %s still pending after %d poll attempts",
            order_id, _POLL_MAX_ATTEMPTS,
        )
        return None
