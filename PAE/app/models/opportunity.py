"""Investment opportunity model."""

from datetime import date, datetime

from sqlalchemy import DECIMAL, Date, ForeignKey, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Opportunity(Base):
    """A validated trade opportunity ready for approval/execution."""

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    primary_strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL")
    )
    confluence_strategy_ids: Mapped[str | None] = mapped_column(Text)  # JSON array
    confluence_score: Mapped[float | None] = mapped_column(DECIMAL(3, 2))
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    thesis: Mapped[str | None] = mapped_column(Text)
    coverage_analysis: Mapped[str | None] = mapped_column(Text)
    catalyst: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[date | None] = mapped_column(Date)
    suggested_amount: Mapped[float | None] = mapped_column(DECIMAL(10, 2))
    suggested_price: Mapped[float | None] = mapped_column(DECIMAL(10, 2))
    stop_loss_pct: Mapped[float | None] = mapped_column(DECIMAL(3, 2))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    primary_strategy: Mapped["Strategy"] = relationship(  # noqa: F821
        foreign_keys=[primary_strategy_id]
    )
    trades: Mapped[list["Trade"]] = relationship(  # noqa: F821
        back_populates="opportunity", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Opportunity id={self.id} ticker={self.ticker!r} "
            f"status={self.status!r}>"
        )
