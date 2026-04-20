"""Thread-related persistence models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base, TimestampMixin, utc_now


class EmailThreadModel(Base, TimestampMixin):
    __tablename__ = "email_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_thread_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    participants_json: Mapped[str] = mapped_column(Text, default="[]")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    latest_message_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    combined_thread_text: Mapped[str] = mapped_column(Text, default="")
    security_status: Mapped[str] = mapped_column(String(32), default="standard")
    sensitivity_markers_json: Mapped[str] = mapped_column(Text, default="[]")
    latest_message_from_me: Mapped[bool] = mapped_column(Boolean, default=False)
    latest_message_from_external: Mapped[bool] = mapped_column(Boolean, default=False)
    latest_message_has_question: Mapped[bool] = mapped_column(Boolean, default=False)
    latest_message_has_action_request: Mapped[bool] = mapped_column(Boolean, default=False)
    waiting_on_us: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_or_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance_score: Mapped[int | None] = mapped_column(Integer)
    relevance_bucket: Mapped[str | None] = mapped_column(String(32))
    included_in_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_decision: Mapped[str | None] = mapped_column(String(64))
    ai_decision_reason: Mapped[str | None] = mapped_column(Text)
    analysis_status: Mapped[str] = mapped_column(String(32), default="pending")
    signature: Mapped[str] = mapped_column(String(128), default="")
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list["ThreadMessageModel"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ThreadMessageModel.sent_at",
    )
    analysis: Mapped["ThreadAnalysisModel | None"] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        uselist=False,
    )
    review: Mapped["ReviewDecisionModel | None"] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        uselist=False,
    )
    state: Mapped["ThreadStateModel | None"] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        uselist=False,
    )
    drafts: Mapped[list["DraftModel"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="DraftModel.created_at.desc()",
    )


class ThreadMessageModel(Base, TimestampMixin):
    __tablename__ = "thread_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("email_threads.id"), index=True)
    external_message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    sender: Mapped[str] = mapped_column(String(500), default="")
    recipients_json: Mapped[str] = mapped_column(Text, default="[]")
    subject: Mapped[str] = mapped_column(String(500), default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snippet: Mapped[str] = mapped_column(Text, default="")
    cleaned_body: Mapped[str] = mapped_column(Text, default="")
    label_ids_json: Mapped[str] = mapped_column(Text, default="[]")

    thread: Mapped["EmailThreadModel"] = relationship(back_populates="messages")


class ThreadAnalysisModel(Base, TimestampMixin):
    __tablename__ = "thread_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("email_threads.id"),
        unique=True,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(64), default="")
    urgency: Mapped[str] = mapped_column(String(32), default="unknown")
    summary: Mapped[str] = mapped_column(Text, default="")
    current_status: Mapped[str] = mapped_column(Text, default="")
    next_action: Mapped[str] = mapped_column(Text, default="")
    needs_action_today: Mapped[bool] = mapped_column(Boolean, default=False)
    should_draft_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    draft_needs_date: Mapped[bool] = mapped_column(Boolean, default=False)
    draft_date_reason: Mapped[str | None] = mapped_column(Text)
    draft_needs_attachment: Mapped[bool] = mapped_column(Boolean, default=False)
    draft_attachment_reason: Mapped[str | None] = mapped_column(Text)
    crm_contact_name: Mapped[str | None] = mapped_column(String(255))
    crm_company: Mapped[str | None] = mapped_column(String(255))
    crm_opportunity_type: Mapped[str | None] = mapped_column(String(255))
    crm_urgency: Mapped[str | None] = mapped_column(String(32))
    provider_name: Mapped[str] = mapped_column(String(64), default="heuristic")
    model_name: Mapped[str] = mapped_column(String(128), default="deterministic-fallback")
    prompt_version: Mapped[str] = mapped_column(String(64), default="v1")
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    thread: Mapped["EmailThreadModel"] = relationship(back_populates="analysis")


class ThreadStateModel(Base, TimestampMixin):
    __tablename__ = "thread_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("email_threads.id"),
        unique=True,
        index=True,
    )
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    seen_version: Mapped[str] = mapped_column(String(128), default="")
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    thread: Mapped["EmailThreadModel"] = relationship(back_populates="state")
