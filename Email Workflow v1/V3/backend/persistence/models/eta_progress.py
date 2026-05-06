"""ETA progress persistence models."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base, TimestampMixin


class EtaProgressModel(Base, TimestampMixin):
    __tablename__ = "eta_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id"), index=True)
    external_thread_id: Mapped[str | None] = mapped_column(String(255), index=True)
    phase_key: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(32), default="sync")
    status: Mapped[str] = mapped_column(String(32), default="running")
    eta_seconds: Mapped[int | None] = mapped_column(Integer)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    details_json: Mapped[str] = mapped_column(Text, default="{}")

    user: Mapped["UserModel"] = relationship(back_populates="eta_progress_entries")
    sync_run: Mapped["SyncRunModel | None"] = relationship(back_populates="eta_progress_entries")
