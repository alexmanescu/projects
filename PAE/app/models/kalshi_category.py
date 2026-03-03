"""Kalshi signal category model — stores suggested and approved search terms."""

from datetime import datetime

from sqlalchemy import TIMESTAMP, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KalshiCategory(Base):
    """A Kalshi search term suggested by the LLM and optionally approved by the user.

    Suggested terms are sent to the user via Telegram.  Replying YES to the
    suggestion message approves the term; NO rejects it.  Approved terms are
    picked up by ``_surface_kalshi_market_signals()`` at the start of each
    detection cycle — no restart required.
    """

    __tablename__ = "kalshi_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="suggested", nullable=False
    )  # "suggested" | "approved" | "rejected"
    source: Mapped[str | None] = mapped_column(String(200))  # what triggered suggestion
    telegram_message_id: Mapped[int | None] = mapped_column()  # for reply-based approval
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
