"""Draft persistence models."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base, TimestampMixin


class DraftModel(Base, TimestampMixin):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("email_threads.id"), index=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    provider_name: Mapped[str] = mapped_column(String(64), default="heuristic")
    model_name: Mapped[str] = mapped_column(String(128), default="deterministic-fallback")
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    # Stored as a JSON-encoded list of KbDraftSource objects. We use a
    # plain Text column rather than a Postgres JSON type so the same
    # schema works on both Postgres (prod) and SQLite (some test setups).
    # Empty string means "no sources" — easier to default than NULL.
    kb_sources_json: Mapped[str] = mapped_column(Text, default="")

    thread: Mapped["EmailThreadModel"] = relationship(back_populates="drafts")
