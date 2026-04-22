"""Persistence model for mutable runtime settings."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.persistence.models.base import Base, TimestampMixin


class RuntimeSettingsModel(Base, TimestampMixin):
    __tablename__ = "runtime_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ai_mode: Mapped[str] = mapped_column(String(32), default="openai")
    local_ai_force_all_threads: Mapped[bool] = mapped_column(Boolean, default=False)
    local_ai_model: Mapped[str] = mapped_column(String(255), default="")
    local_ai_agent_prompt: Mapped[str] = mapped_column(Text, default="")
