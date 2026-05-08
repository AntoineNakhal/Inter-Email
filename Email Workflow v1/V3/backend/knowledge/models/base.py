"""Declarative base for the KB database.

Distinct from `backend.persistence.models.base.Base` so Alembic --autogenerate
on the main DB never picks up KB tables (and vice-versa).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KbBase(DeclarativeBase):
    """Base class for all Knowledge Base SQLAlchemy models."""


class KbTimestampMixin:
    """Shared timestamp columns (mirrors the main DB's TimestampMixin)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
