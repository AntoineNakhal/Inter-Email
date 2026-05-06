"""Sync run persistence model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base, TimestampMixin


class SyncRunModel(Base, TimestampMixin):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    source: Mapped[str] = mapped_column(String(32), default="anywhere")
    # Gmail address that owns this run — enforces single-active-run-per-account.
    mailbox_account: Mapped[str] = mapped_column(String(255), default="")
    fetched_message_count: Mapped[int] = mapped_column(Integer, default=0)
    thread_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_thread_count: Mapped[int] = mapped_column(Integer, default=0)
    queue_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    # JSON snapshot written at each stage transition (stage, percent, unit counts,
    # status_message). Allows a restarted process to surface last-known state.
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    user: Mapped["UserModel"] = relationship(back_populates="sync_runs")
    eta_progress_entries: Mapped[list["EtaProgressModel"]] = relationship(
        back_populates="sync_run",
        cascade="all, delete-orphan",
    )
