"""Strategy registration model."""

from datetime import datetime

from sqlalchemy import Boolean, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Strategy(Base):
    """Registered trading strategy."""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    version: Mapped[str | None] = mapped_column(String(50))
    thesis_md_path: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    articles: Mapped[list["ArticleRegistry"]] = relationship(  # noqa: F821
        back_populates="first_strategy"
    )
    analyses: Mapped[list["ArticleAnalysis"]] = relationship(  # noqa: F821
        back_populates="strategy"
    )
    signals: Mapped[list["Signal"]] = relationship(  # noqa: F821
        back_populates="strategy"
    )

    def __repr__(self) -> str:
        return f"<Strategy id={self.id} name={self.name!r} active={self.is_active}>"
