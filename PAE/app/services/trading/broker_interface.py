"""Abstract base class for broker integrations.

All broker implementations must inherit from :class:`BrokerInterface` and
implement every abstract method.  The contract is intentionally minimal so
that paper-trading stubs and real brokers can share the same call-sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ── Value objects ──────────────────────────────────────────────────────────────

@dataclass
class AccountInfo:
    """Snapshot of broker account state."""
    cash: float
    portfolio_value: float
    buying_power: float
    currency: str = "USD"
    account_number: str = ""
    is_paper: bool = True
    raw: dict = field(default_factory=dict)  # broker-native response for debugging


@dataclass
class BrokerPosition:
    """A single open position as reported by the broker."""
    ticker: str
    quantity: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    raw: dict = field(default_factory=dict)


@dataclass
class OrderResult:
    """Result returned after submitting an order."""
    order_id: str
    ticker: str
    action: str          # "buy" or "sell"
    quantity: float
    filled_price: float | None  # None if not yet filled
    status: str          # "filled", "pending", "cancelled", "rejected"
    raw: dict = field(default_factory=dict)


# ── Abstract interface ─────────────────────────────────────────────────────────

class BrokerInterface(ABC):
    """Protocol that every broker adapter must implement."""

    # ── Account ───────────────────────────────────────────────────────────────

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """Return current account balances and buying power."""
        ...

    # ── Positions ─────────────────────────────────────────────────────────────

    @abstractmethod
    def get_current_positions(self) -> list[BrokerPosition]:
        """Return all open positions held in the broker account."""
        ...

    # ── Market data ───────────────────────────────────────────────────────────

    @abstractmethod
    def get_current_price(self, ticker: str) -> float:
        """Return the latest trade/quote price for *ticker*.

        Raises:
            BrokerError: If the price cannot be retrieved.
        """
        ...

    # ── Order execution ───────────────────────────────────────────────────────

    @abstractmethod
    def execute_buy(
        self,
        ticker: str,
        shares: float,
        stop_loss_pct: float | None = None,
    ) -> OrderResult:
        """Submit a market buy order for *shares* of *ticker*.

        Implementations should:
        1. Submit a market order.
        2. Poll for fill confirmation (up to ~10 seconds).
        3. Optionally attach a stop-loss order once filled.

        Args:
            ticker: Ticker symbol.
            shares: Number of shares to buy (may be fractional).
            stop_loss_pct: If provided, attach a stop-loss at
                ``fill_price * (1 - stop_loss_pct)``.

        Returns:
            :class:`OrderResult` with ``status="filled"`` on success.

        Raises:
            BrokerError: On order rejection or network failure.
        """
        ...

    @abstractmethod
    def execute_sell(self, ticker: str, shares: float) -> OrderResult:
        """Submit a market sell order for *shares* of *ticker*.

        Args:
            ticker: Ticker symbol.
            shares: Number of shares to sell.

        Returns:
            :class:`OrderResult` with ``status="filled"`` on success.

        Raises:
            BrokerError: On order rejection or network failure.
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order by ID.

        Returns:
            ``True`` if the cancellation was accepted, ``False`` if the order
            was already filled or not found.
        """
        ...


# ── Exceptions ────────────────────────────────────────────────────────────────

class BrokerError(Exception):
    """Raised for unrecoverable broker API errors."""


class OrderRejectedError(BrokerError):
    """Raised when the broker explicitly rejects an order."""


class InsufficientFundsError(BrokerError):
    """Raised when buying power is too low to place the order."""
