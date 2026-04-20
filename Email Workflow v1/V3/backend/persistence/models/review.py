"""Review persistence models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base, TimestampMixin


class ReviewDecisionModel(Base, TimestampMixin):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("email_threads.id"),
        unique=True,
        index=True,
    )
    queue_belongs: Mapped[str] = mapped_column(String(32), default="not_sure")
    merge_correct: Mapped[str] = mapped_column(String(32), default="not_sure")
    summary_useful: Mapped[str] = mapped_column(String(32), default="partially")
    next_action_useful: Mapped[str] = mapped_column(String(32), default="partially")
    draft_useful: Mapped[str] = mapped_column(String(32), default="partially")
    crm_useful: Mapped[str] = mapped_column(String(32), default="not_applicable")
    notes: Mapped[str] = mapped_column(Text, default="")
    improvement_tags_json: Mapped[str] = mapped_column(Text, default="[]")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    thread: Mapped["EmailThreadModel"] = relationship(back_populates="review")
