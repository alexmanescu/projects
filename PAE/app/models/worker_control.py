"""Worker control model — stores pause/resume state for each worker."""

from datetime import datetime

from sqlalchemy import Boolean, String, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WorkerControl(Base):
    """Pause/resume flag for a named worker.

    The primary key is ``worker_name`` so each worker has exactly one row.
    Workers are created with ``paused=False`` on first use.

    Valid worker names: ``"scrape"``, ``"detect"``.
    """

    __tablename__ = "worker_controls"

    worker_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(String(100))  # "telegram" or "system"

    def __repr__(self) -> str:
        state = "PAUSED" if self.paused else "running"
        return f"<WorkerControl {self.worker_name}={state}>"
