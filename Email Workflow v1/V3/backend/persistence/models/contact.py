"""SQLAlchemy models for the contacts/persona system."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base


class ContactModel(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    contact_type: Mapped[str] = mapped_column(
        String(32), default="external", nullable=False
    )
    # When True the user has manually set the type — auto-detection won't overwrite.
    type_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    organization: Mapped[str] = mapped_column(String(256), default="")
    # Cached count — updated on every upsert for fast queries.
    thread_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    thread_links: Mapped[list[ContactThreadModel]] = relationship(
        "ContactThreadModel", back_populates="contact", cascade="all, delete-orphan"
    )


class ContactThreadModel(Base):
    __tablename__ = "contact_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_thread_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    # "sender" | "recipient"
    role: Mapped[str] = mapped_column(String(16), default="recipient")
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    contact: Mapped[ContactModel] = relationship("ContactModel", back_populates="thread_links")
