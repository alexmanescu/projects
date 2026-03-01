"""Article registry and analysis models."""

from datetime import datetime

from sqlalchemy import (
    DECIMAL, Enum, ForeignKey, Index, Integer, String, Text, TIMESTAMP, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

_MatchType = Enum("url_match", "content_match", "fuzzy_match", name="match_type_enum")


class ArticleRegistry(Base):
    """Canonical record for every unique article ever scraped."""

    __tablename__ = "article_registry"
    __table_args__ = (
        Index("ix_article_registry_content_hash", "content_hash"),
        Index("ix_article_registry_last_seen_at", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    content_db: Mapped[str | None] = mapped_column(String(255))
    content_table: Mapped[str | None] = mapped_column(String(255))
    content_id: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(32))
    first_scraped_by: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL")
    )
    first_scraped_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    scrape_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    first_strategy: Mapped["Strategy"] = relationship(  # noqa: F821
        back_populates="articles", foreign_keys=[first_scraped_by]
    )
    aliases: Mapped[list["ArticleUrlAlias"]] = relationship(
        back_populates="registry_entry", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["ArticleAnalysis"]] = relationship(
        back_populates="registry_entry", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ArticleRegistry id={self.id} hash={self.content_hash!r}>"


class ArticleUrlAlias(Base):
    """Alternative URLs that resolve to the same canonical article."""

    __tablename__ = "article_url_aliases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url: Mapped[str | None] = mapped_column(Text)
    canonical_registry_id: Mapped[int | None] = mapped_column(
        ForeignKey("article_registry.id", ondelete="CASCADE")
    )
    match_type: Mapped[str | None] = mapped_column(_MatchType)
    matched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    registry_entry: Mapped["ArticleRegistry"] = relationship(back_populates="aliases")

    def __repr__(self) -> str:
        return (
            f"<ArticleUrlAlias id={self.id} type={self.match_type!r} "
            f"canonical={self.canonical_registry_id}>"
        )


class ArticleAnalysis(Base):
    """LLM/rule-based analysis result for one article under one strategy."""

    __tablename__ = "article_analysis"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    registry_id: Mapped[int | None] = mapped_column(
        ForeignKey("article_registry.id", ondelete="CASCADE")
    )
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL")
    )
    relevance_score: Mapped[float | None] = mapped_column(DECIMAL(3, 2))
    sentiment_score: Mapped[float | None] = mapped_column(DECIMAL(3, 2))
    signal_strength: Mapped[float | None] = mapped_column(DECIMAL(3, 2))
    entities_detected: Mapped[str | None] = mapped_column(Text)   # JSON
    topics_detected: Mapped[str | None] = mapped_column(Text)     # JSON
    thesis_notes: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    registry_entry: Mapped["ArticleRegistry"] = relationship(back_populates="analyses")
    strategy: Mapped["Strategy"] = relationship(  # noqa: F821
        back_populates="analyses", foreign_keys=[strategy_id]
    )

    def __repr__(self) -> str:
        return (
            f"<ArticleAnalysis id={self.id} registry={self.registry_id} "
            f"relevance={self.relevance_score}>"
        )
