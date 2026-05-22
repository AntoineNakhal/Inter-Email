"""Email account persistence model.

One user can have many connected email accounts across multiple providers.
Credentials are Fernet-encrypted before storage, same key as the existing
gmail_token_encrypted field on UserModel.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.persistence.models.base import Base, TimestampMixin


class EmailAccountModel(Base, TimestampMixin):
    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # Provider slug: 'gmail' | 'outlook' | 'icloud' | 'imap'
    provider: Mapped[str] = mapped_column(String(20), nullable=False)

    # The email address this account reads from
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))

    # Fernet-encrypted JSON blob. Schema varies by provider:
    #   gmail/outlook → {"access_token":..., "refresh_token":..., "token_uri":..., ...}
    #   icloud/imap   → {"host":..., "port":..., "username":..., "password":...}
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="email_accounts")
