"""User and auth session persistence models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base, TimestampMixin


class UserModel(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(32), default="user")
    # email/password auth — nullable so existing Google-only users aren't broken
    password_hash: Mapped[str | None] = mapped_column(Text)
    # kept for backwards-compat during migration; new connections use email_accounts
    google_subject: Mapped[str | None] = mapped_column(String(255))
    gmail_token_encrypted: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["UserSessionModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    email_accounts: Mapped[list["EmailAccountModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    settings: Mapped["RuntimeSettingsModel | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    threads: Mapped[list["EmailThreadModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    contacts: Mapped[list["ContactModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sync_runs: Mapped[list["SyncRunModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    eta_progress_entries: Mapped[list["EtaProgressModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserSessionModel(Base, TimestampMixin):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[UserModel] = relationship(back_populates="sessions")
