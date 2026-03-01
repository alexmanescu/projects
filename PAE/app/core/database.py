"""SQLAlchemy engine and session management for MySQL."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,       # detect stale connections
    pool_recycle=3600,        # recycle connections every hour
    echo=(settings.log_level == "DEBUG"),
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Provide a transactional database session.

    Usage::

        with db_session() as session:
            session.add(obj)
            session.commit()
    """
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables that don't yet exist in the database.

    Safe to call on every startup — only creates missing tables.
    """
    # Import all models so their metadata is registered before create_all.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def ping_db() -> bool:
    """Return True if the database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
