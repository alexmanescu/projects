"""Current open positions model."""

from datetime import datetime

from sqlalchemy import DECIMAL, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Position(Base):
    """Live position tracker — one row per unique ticker."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    quantity: Mapped[float | None] = mapped_column(DECIMAL(10, 4))
    avg_entry_price: Mapped[float | None] = mapped_column(DECIMAL(10, 2))
    current_price: Mapped[float | None] = mapped_column(DECIMAL(10, 2))
    stop_loss: Mapped[float | None] = mapped_column(DECIMAL(10, 2))
    thesis: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False
    )
    last_updated: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def unrealized_pnl_pct(self) -> float | None:
        """Percentage gain/loss vs average entry price."""
        if self.avg_entry_price and self.current_price and self.avg_entry_price != 0:
            return (self.current_price - self.avg_entry_price) / self.avg_entry_price * 100
        return None

    def __repr__(self) -> str:
        return (
            f"<Position ticker={self.ticker!r} qty={self.quantity} "
            f"entry={self.avg_entry_price}>"
        )
