"""Persistence model for mutable runtime settings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base, TimestampMixin


class RuntimeSettingsModel(Base, TimestampMixin):
    __tablename__ = "runtime_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True,
        index=True,
    )
    ai_mode: Mapped[str] = mapped_column(String(32), default="openai")
    local_ai_force_all_threads: Mapped[bool] = mapped_column(Boolean, default=False)
    local_ai_model: Mapped[str] = mapped_column(String(255), default="")
    local_ai_agent_prompt: Mapped[str] = mapped_column(Text, default="")
    gmail_mailbox_email: Mapped[str] = mapped_column(String(255), default="")
    gmail_mailbox_name: Mapped[str] = mapped_column(String(255), default="")
    # Gmail history cursor — the historyId returned by the last successful sync.
    # When non-empty, the sync service calls users.history.list(startHistoryId=...)
    # instead of a full rolling-window fetch.
    gmail_history_id: Mapped[str] = mapped_column(String(255), default="")
    # Pub/Sub watch state — populated after users.watch() succeeds.
    gmail_watch_resource_id: Mapped[str] = mapped_column(String(255), default="")
    gmail_watch_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    local_ai_max_threads: Mapped[int] = mapped_column(Integer, default=50)

    user: Mapped["UserModel"] = relationship(back_populates="settings")
