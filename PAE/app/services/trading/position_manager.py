"""Position sizing, validation, and stop-loss calculation.

``PositionManager`` is the single decision-making layer between a trading
signal and an actual broker call.  It enforces portfolio-level risk limits
and translates conviction levels into share counts.

Conviction → position size (% of portfolio equity):
    ``"low"``    → 5 %
    ``"medium"`` → 10 %
    ``"high"``   → 15 %

Hard limits (not configurable at runtime):
    - Maximum 10 concurrent open positions.
    - Total market exposure may not exceed 90 % of portfolio equity.
    - ``stop_loss_pct`` must be between 1 % and 25 %.
"""

from __future__ import annotations

import logging
import math
from typing import Literal

from app.services.trading.broker_interface import (
    AccountInfo,
    BrokerInterface,
    BrokerPosition,
)

logger = logging.getLogger(__name__)

ConvictionLevel = Literal["low", "medium", "high"]

# ── Constants ─────────────────────────────────────────────────────────────────

_CONVICTION_SIZE: dict[str, float] = {
    "low": 0.05,
    "medium": 0.10,
    "high": 0.15,
}
_MAX_POSITIONS = 10
_MAX_EXPOSURE_RATIO = 0.90
_MIN_STOP_LOSS_PCT = 0.01
_MAX_STOP_LOSS_PCT = 0.25


# ── Validation result ─────────────────────────────────────────────────────────

class TradeValidationError(Exception):
    """Raised by :meth:`PositionManager.validate_trade` when a trade is blocked."""


# ── Manager ───────────────────────────────────────────────────────────────────

class PositionManager:
    """Stateless risk-management helper that wraps a :class:`BrokerInterface`.

    All public methods query the broker for real-time account state on every
    call — there is intentionally no caching so that sequential calls within
    the same cycle always reflect the latest broker snapshot.
    """

    def __init__(self, broker: BrokerInterface) -> None:
        self._broker = broker

    # ── Public API ────────────────────────────────────────────────────────────

    def can_add_position(self) -> tuple[bool, str]:
        """Return ``(True, "")`` if a new position may be opened.

        Checks:
        1. Open position count < :data:`_MAX_POSITIONS`.
        2. Current exposure < :data:`_MAX_EXPOSURE_RATIO` × portfolio equity.

        Returns:
            A tuple ``(allowed, reason)``.  If *allowed* is ``False``,
            *reason* explains which limit was hit.
        """
        try:
            positions = self._broker.get_current_positions()
            account = self._broker.get_account_info()
        except Exception as exc:
            return False, f"Broker query failed: {exc}"

        if len(positions) >= _MAX_POSITIONS:
            return False, (
                f"Max position limit reached ({len(positions)}/{_MAX_POSITIONS})"
            )

        current_exposure = sum(p.market_value for p in positions)
        max_allowed_exposure = account.portfolio_value * _MAX_EXPOSURE_RATIO
        if current_exposure >= max_allowed_exposure:
            return False, (
                f"Exposure limit reached: ${current_exposure:,.0f} / "
                f"${max_allowed_exposure:,.0f} "
                f"({_MAX_EXPOSURE_RATIO * 100:.0f}% of portfolio)"
            )

        return True, ""

    def calculate_shares(
        self,
        ticker: str,
        conviction: ConvictionLevel,
    ) -> float:
        """Return the number of (whole) shares to buy for a given conviction.

        The target dollar allocation is ``portfolio_value × conviction_pct``.
        Shares are rounded **down** to the nearest whole share so we never
        over-allocate.  Returns 0 if the allocation is smaller than one share.

        Args:
            ticker: Ticker to price.
            conviction: ``"low"``, ``"medium"``, or ``"high"``.

        Returns:
            Number of whole shares (float, but always integer-valued, ≥ 0).

        Raises:
            :class:`TradeValidationError`: If conviction is unknown or the
                broker cannot be queried.
        """
        size_pct = _CONVICTION_SIZE.get(conviction)
        if size_pct is None:
            raise TradeValidationError(
                f"Unknown conviction level: {conviction!r}. "
                f"Must be one of {list(_CONVICTION_SIZE)}"
            )

        try:
            account = self._broker.get_account_info()
            price = self._broker.get_current_price(ticker)
        except Exception as exc:
            raise TradeValidationError(
                f"Cannot calculate shares — broker error: {exc}"
            ) from exc

        if price <= 0:
            raise TradeValidationError(
                f"Invalid price for {ticker}: {price}"
            )

        target_dollars = account.portfolio_value * size_pct
        shares = math.floor(target_dollars / price)
        logger.debug(
            "calculate_shares(%s, %s): $%.0f × %.0f%% = $%.0f / $%.2f = %d shares",
            ticker, conviction,
            account.portfolio_value, size_pct * 100,
            target_dollars, price, shares,
        )
        return float(shares)

    def calculate_stop_loss(
        self,
        entry_price: float,
        stop_loss_pct: float,
    ) -> float:
        """Return the stop-loss price for an entry at *entry_price*.

        Args:
            entry_price: Fill price of the buy order.
            stop_loss_pct: Fraction below entry to place the stop
                (e.g. ``0.05`` for a 5 % stop).

        Returns:
            Stop price rounded to two decimal places.

        Raises:
            :class:`TradeValidationError`: If the percentage is outside the
                allowed range.
        """
        if not (_MIN_STOP_LOSS_PCT <= stop_loss_pct <= _MAX_STOP_LOSS_PCT):
            raise TradeValidationError(
                f"stop_loss_pct={stop_loss_pct:.2%} is outside the allowed "
                f"range [{_MIN_STOP_LOSS_PCT:.0%}, {_MAX_STOP_LOSS_PCT:.0%}]"
            )
        return round(entry_price * (1.0 - stop_loss_pct), 2)

    def validate_trade(
        self,
        ticker: str,
        conviction: ConvictionLevel,
        stop_loss_pct: float = 0.05,
    ) -> dict:
        """Run all pre-trade validations and return a sizing summary.

        This is the primary entry point before calling
        :meth:`~broker_interface.BrokerInterface.execute_buy`.

        Steps:
        1. Check position and exposure limits.
        2. Calculate share count.
        3. Validate stop-loss percentage.
        4. Verify adequate buying power.

        Args:
            ticker: Ticker to validate.
            conviction: Position sizing key.
            stop_loss_pct: Stop distance as a fraction of entry price.

        Returns:
            Dict with keys:
            - ``ticker``
            - ``conviction``
            - ``shares``           — calculated share count
            - ``estimated_cost``   — shares × current price
            - ``stop_loss_pct``    — validated stop distance
            - ``portfolio_pct``    — fraction of portfolio being deployed

        Raises:
            :class:`TradeValidationError`: If any validation fails.
        """
        allowed, reason = self.can_add_position()
        if not allowed:
            raise TradeValidationError(reason)

        shares = self.calculate_shares(ticker, conviction)
        if shares < 1:
            raise TradeValidationError(
                f"Allocation for {ticker!r} at conviction={conviction!r} "
                f"rounds to 0 shares — price may be too high for the portfolio size"
            )

        # Validate stop-loss range (will raise on invalid range)
        self.calculate_stop_loss(1.0, stop_loss_pct)

        try:
            price = self._broker.get_current_price(ticker)
            account = self._broker.get_account_info()
        except Exception as exc:
            raise TradeValidationError(f"Broker query failed: {exc}") from exc

        estimated_cost = shares * price
        if estimated_cost > account.buying_power:
            raise TradeValidationError(
                f"Insufficient buying power: need ${estimated_cost:,.2f}, "
                f"have ${account.buying_power:,.2f}"
            )

        portfolio_pct = _CONVICTION_SIZE[conviction]
        logger.info(
            "validate_trade(%s, %s): %d shares @ $%.2f = $%.0f "
            "(%.0f%% of portfolio, stop=%.1f%%)",
            ticker, conviction, shares, price, estimated_cost,
            portfolio_pct * 100, stop_loss_pct * 100,
        )

        return {
            "ticker": ticker,
            "conviction": conviction,
            "shares": shares,
            "estimated_cost": estimated_cost,
            "stop_loss_pct": stop_loss_pct,
            "portfolio_pct": portfolio_pct,
        }

    def get_position_summary(self) -> dict:
        """Return a snapshot of current portfolio exposure.

        Returns:
            Dict with keys:
            - ``position_count``
            - ``max_positions``
            - ``total_exposure``   — sum of all position market values
            - ``portfolio_value``
            - ``exposure_ratio``   — fraction of portfolio currently invested
            - ``available_slots``  — how many more positions can be added
            - ``can_trade``        — bool shorthand
        """
        try:
            positions = self._broker.get_current_positions()
            account = self._broker.get_account_info()
        except Exception as exc:
            logger.error("get_position_summary failed: %s", exc)
            return {}

        total_exposure = sum(p.market_value for p in positions)
        exposure_ratio = total_exposure / account.portfolio_value if account.portfolio_value else 0
        available_slots = max(0, _MAX_POSITIONS - len(positions))
        can_trade = (
            available_slots > 0
            and exposure_ratio < _MAX_EXPOSURE_RATIO
        )

        return {
            "position_count": len(positions),
            "max_positions": _MAX_POSITIONS,
            "total_exposure": total_exposure,
            "portfolio_value": account.portfolio_value,
            "exposure_ratio": exposure_ratio,
            "available_slots": available_slots,
            "can_trade": can_trade,
        }
