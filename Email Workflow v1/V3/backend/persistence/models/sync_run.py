"""Sync run persistence model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.persistence.models.base import Base, TimestampMixin


class SyncRunModel(Base, TimestampMixin):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    source: Mapped[str] = mapped_column(String(32), default="anywhere")
    fetched_message_count: Mapped[int] = mapped_column(Integer, default=0)
    thread_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_thread_count: Mapped[int] = mapped_column(Integer, default=0)
    queue_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
