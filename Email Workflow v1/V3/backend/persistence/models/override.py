"""Thread override persistence model."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base, TimestampMixin


class ThreadOverrideModel(Base, TimestampMixin):
    """Stores per-user manual corrections to AI-generated thread analysis fields.

    One row per (user, thread) — upserted on every save.
    Nullable columns mean "not overridden by user" — the AI value is used.
    """

    __tablename__ = "thread_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("email_threads.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # Overridable fields — None means "not set by user"
    category: Mapped[str | None] = mapped_column(String(64))
    urgency: Mapped[str | None] = mapped_column(String(32))
    needs_action_today: Mapped[bool | None] = mapped_column(Boolean)
    waiting_on_us: Mapped[bool | None] = mapped_column(Boolean)
    needs_next_action: Mapped[bool | None] = mapped_column(Boolean)
    should_draft_reply: Mapped[bool | None] = mapped_column(Boolean)
    relevance_bucket: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str] = mapped_column(Text, default="")

    thread: Mapped["EmailThreadModel"] = relationship(back_populates="override")
    user: Mapped["UserModel"] = relationship()
