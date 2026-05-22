"""CRUD helpers for connected email accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.persistence.models.email_account import EmailAccountModel


@dataclass(slots=True)
class EmailAccountRecord:
    id: int
    user_id: int
    provider: str          # 'gmail' | 'outlook' | 'icloud' | 'imap'
    email_address: str
    display_name: str | None
    is_active: bool
    created_at: datetime | None
    # credentials_encrypted intentionally NOT exposed here; fetch via get_model_by_id


class EmailAccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_user(self, user_id: int) -> list[EmailAccountRecord]:
        models = self.session.scalars(
            select(EmailAccountModel).where(
                EmailAccountModel.user_id == user_id,
                EmailAccountModel.is_active == True,  # noqa: E712
            )
        ).all()
        return [self._to_record(m) for m in models]

    def get_by_id(self, account_id: int, user_id: int) -> EmailAccountRecord | None:
        model = self._find(account_id, user_id)
        return self._to_record(model) if model else None

    def get_model_by_id(self, account_id: int, user_id: int) -> EmailAccountModel | None:
        return self._find(account_id, user_id)

    def create(
        self,
        *,
        user_id: int,
        provider: str,
        email_address: str,
        display_name: str | None,
        credentials_encrypted: str | None,
    ) -> EmailAccountRecord:
        model = EmailAccountModel(
            user_id=user_id,
            provider=provider,
            email_address=email_address.strip().lower(),
            display_name=display_name,
            credentials_encrypted=credentials_encrypted,
            is_active=True,
        )
        self.session.add(model)
        self.session.flush()
        return self._to_record(model)

    def update_credentials(self, account_id: int, user_id: int, credentials_encrypted: str) -> None:
        model = self._find(account_id, user_id)
        if model:
            model.credentials_encrypted = credentials_encrypted
            self.session.flush()

    def deactivate(self, account_id: int, user_id: int) -> bool:
        """Soft-delete. Returns True if found and deactivated."""
        model = self._find(account_id, user_id)
        if model is None:
            return False
        model.is_active = False
        self.session.flush()
        return True

    def list_active_for_provider(self, provider: str) -> list[EmailAccountModel]:
        """Used by sync runner to iterate all active accounts for a provider."""
        return list(self.session.scalars(
            select(EmailAccountModel).where(
                EmailAccountModel.provider == provider,
                EmailAccountModel.is_active == True,  # noqa: E712
            )
        ).all())

    def list_models_for_user(self, user_id: int) -> list[EmailAccountModel]:
        """Return raw model objects (including encrypted credentials) for all
        active accounts of a user. Used by the supplemental sync to access
        credentials for non-Gmail providers."""
        return list(self.session.scalars(
            select(EmailAccountModel).where(
                EmailAccountModel.user_id == user_id,
                EmailAccountModel.is_active == True,  # noqa: E712
            )
        ).all())

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _find(self, account_id: int, user_id: int) -> EmailAccountModel | None:
        return self.session.scalar(
            select(EmailAccountModel).where(
                EmailAccountModel.id == account_id,
                EmailAccountModel.user_id == user_id,
            )
        )

    @staticmethod
    def _to_record(model: EmailAccountModel) -> EmailAccountRecord:
        return EmailAccountRecord(
            id=model.id,
            user_id=model.user_id,
            provider=model.provider,
            email_address=model.email_address,
            display_name=model.display_name,
            is_active=model.is_active,
            created_at=model.created_at,
        )
