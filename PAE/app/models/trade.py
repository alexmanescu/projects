"""Trade execution log model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DECIMAL, Boolean, ForeignKey, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class Trade(Base):
    """Record of a single trade execution (entry or exit)."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL")
    )
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL")
    )
    ticker: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str | None] = mapped_column(String(10))       # buy / sell
    quantity: Mapped[float | None] = mapped_column(DECIMAL(10, 4))
    entry_price: Mapped[float | None] = mapped_column(DECIMAL(10, 2))
    exit_price: Mapped[float | None] = mapped_column(DECIMAL(10, 2))
    stop_loss: Mapped[float | None] = mapped_column(DECIMAL(10, 2))
    return_pct: Mapped[float | None] = mapped_column(DECIMAL(5, 2))
    approved: Mapped[bool | None] = mapped_column(Boolean)
    executed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    closed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    notes: Mapped[str | None] = mapped_column(Text)

    # ── Relationships ─────────────────────────────────────────────────────────
    opportunity: Mapped["Opportunity"] = relationship(  # noqa: F821
        back_populates="trades", foreign_keys=[opportunity_id]
    )
    strategy: Mapped["Strategy"] = relationship(  # noqa: F821
        foreign_keys=[strategy_id]
    )

    # ── Classmethods ──────────────────────────────────────────────────────────

    @classmethod
    def log_execution(
        cls,
        db: Session,
        *,
        ticker: str,
        action: str,
        quantity: float,
        price: float,
        stop_loss: float | None = None,
        opportunity_id: int | None = None,
        strategy_id: int | None = None,
        notes: str | None = None,
    ) -> "Trade":
        """Insert a new trade execution row and flush (caller commits).

        Args:
            db: Active SQLAlchemy session.
            ticker: Ticker symbol (e.g. ``"NVDA"``).
            action: ``"buy"`` or ``"sell"``.
            quantity: Number of shares.
            price: Fill price.
            stop_loss: Optional stop-loss price.
            opportunity_id: FK to the originating opportunity row.
            strategy_id: FK to the strategy row.
            notes: Free-text annotation (e.g. order ID from broker).

        Returns:
            The newly created :class:`Trade` instance with ``id`` populated.
        """
        field = "entry_price" if action.lower() == "buy" else "exit_price"
        row = cls(
            ticker=ticker,
            action=action.lower(),
            quantity=quantity,
            entry_price=price if action.lower() == "buy" else None,
            exit_price=price if action.lower() == "sell" else None,
            stop_loss=stop_loss,
            opportunity_id=opportunity_id,
            strategy_id=strategy_id,
            approved=True,
            executed_at=datetime.now(tz=timezone.utc),
            notes=notes,
        )
        db.add(row)
        db.flush()
        return row

    @classmethod
    def get_active_trades(cls, db: Session) -> list["Trade"]:
        """Return all buy-side trades that have not yet been closed.

        A trade is considered open when ``exit_price`` is NULL and
        ``closed_at`` is NULL.
        """
        return (
            db.query(cls)
            .filter(
                cls.action == "buy",
                cls.exit_price.is_(None),
                cls.closed_at.is_(None),
            )
            .all()
        )

    @classmethod
    def calculate_returns(cls, db: Session) -> dict:
        """Return aggregate return metrics across all closed trades.

        Returns a dict with keys:
        - ``total_trades``: number of closed trades
        - ``winning_trades``: trades with ``return_pct > 0``
        - ``losing_trades``: trades with ``return_pct < 0``
        - ``win_rate``: fraction of winning trades (0.0–1.0), or ``None``
        - ``avg_return_pct``: mean return across closed trades, or ``None``
        - ``total_return_pct``: sum of all ``return_pct`` values
        """
        closed = (
            db.query(cls)
            .filter(
                cls.return_pct.is_not(None),
                cls.closed_at.is_not(None),
            )
            .all()
        )
        if not closed:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": None,
                "avg_return_pct": None,
                "total_return_pct": 0.0,
            }

        returns = [float(t.return_pct) for t in closed]
        winning = sum(1 for r in returns if r > 0)
        losing = sum(1 for r in returns if r < 0)
        total = len(returns)
        return {
            "total_trades": total,
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": winning / total,
            "avg_return_pct": sum(returns) / total,
            "total_return_pct": sum(returns),
        }

    def __repr__(self) -> str:
        return (
            f"<Trade id={self.id} ticker={self.ticker!r} "
            f"action={self.action!r} approved={self.approved}>"
        )
