"""User and auth session persistence helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.user import AuthenticatedUser, UserRole
from backend.persistence.models.user import UserModel, UserSessionModel


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ #
    # Read helpers                                                         #
    # ------------------------------------------------------------------ #

    def get_by_id(self, user_id: int) -> AuthenticatedUser | None:
        model = self.session.get(UserModel, user_id)
        if model is None or not model.is_active:
            return None
        return self._to_domain(model)

    def get_model_by_id(self, user_id: int) -> UserModel | None:
        model = self.session.get(UserModel, user_id)
        if model is None or not model.is_active:
            return None
        return model

    def get_by_email(self, email: str) -> AuthenticatedUser | None:
        model = self._find_by_email(email)
        if model is None or not model.is_active:
            return None
        return self._to_domain(model)

    def get_model_by_email(self, email: str) -> UserModel | None:
        model = self._find_by_email(email)
        if model is None or not model.is_active:
            return None
        return model

    # ------------------------------------------------------------------ #
    # Write helpers — email/password auth                                  #
    # ------------------------------------------------------------------ #

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        role: UserRole,
        password_hash: str,
    ) -> AuthenticatedUser:
        """Create a brand-new user account. Raises ValueError if email taken."""
        normalized_email = str(email or "").strip().lower()
        if self._find_by_email(normalized_email) is not None:
            raise ValueError("An account with that email already exists.")
        model = UserModel(
            email=normalized_email,
            display_name=str(display_name or "").strip(),
            role=role.value,
            password_hash=password_hash,
            is_active=True,
            last_login_at=datetime.now(timezone.utc),
        )
        self.session.add(model)
        self.session.flush()
        return self._to_domain(model)

    def update_last_login(self, user_id: int) -> None:
        model = self.session.get(UserModel, user_id)
        if model:
            model.last_login_at = datetime.now(timezone.utc)
            self.session.flush()

    # ------------------------------------------------------------------ #
    # Write helpers — legacy Google OAuth (kept for backwards compat)      #
    # ------------------------------------------------------------------ #

    def upsert_google_user(
        self,
        *,
        email: str,
        display_name: str,
        role: UserRole,
        google_subject: str | None,
        gmail_token_encrypted: str,
    ) -> AuthenticatedUser:
        normalized_email = str(email or "").strip().lower()
        model = self._find_by_email(normalized_email)
        if model is None:
            model = UserModel(
                email=normalized_email,
                display_name=str(display_name or "").strip(),
                role=role.value,
                google_subject=str(google_subject or "").strip() or None,
                gmail_token_encrypted=gmail_token_encrypted,
                is_active=True,
            )
            self.session.add(model)
        else:
            model.display_name = str(display_name or "").strip()
            model.role = role.value
            model.google_subject = str(google_subject or "").strip() or None
            model.gmail_token_encrypted = gmail_token_encrypted
            model.is_active = True
        model.last_login_at = datetime.now(timezone.utc)
        self.session.flush()
        return self._to_domain(model)

    # ------------------------------------------------------------------ #
    # Session management                                                   #
    # ------------------------------------------------------------------ #

    def create_session(
        self,
        *,
        user_id: int,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> None:
        model = UserSessionModel(
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            last_used_at=datetime.now(timezone.utc),
        )
        self.session.add(model)
        self.session.flush()

    def get_session(self, refresh_token_hash: str) -> UserSessionModel | None:
        return self.session.scalar(
            select(UserSessionModel).where(
                UserSessionModel.refresh_token_hash == refresh_token_hash,
            )
        )

    def touch_session(self, session_model: UserSessionModel) -> None:
        session_model.last_used_at = datetime.now(timezone.utc)
        self.session.flush()

    def revoke_session(self, refresh_token_hash: str) -> None:
        model = self.get_session(refresh_token_hash)
        if model is None or model.revoked_at is not None:
            return
        model.revoked_at = datetime.now(timezone.utc)
        self.session.flush()

    def list_connected_users(self) -> list[AuthenticatedUser]:
        """Legacy: users with a gmail_token directly on the user row."""
        models = self.session.scalars(
            select(UserModel).where(
                UserModel.is_active == True,  # noqa: E712
                UserModel.gmail_token_encrypted.is_not(None),
            )
        ).all()
        return [self._to_domain(model) for model in models]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_domain(model: UserModel) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=model.id,
            email=model.email,
            display_name=model.display_name,
            role=model.role,
            google_subject=model.google_subject,
            last_login_at=model.last_login_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _find_by_email(self, email: str) -> UserModel | None:
        normalized_email = str(email or "").strip().lower()
        return self.session.scalar(
            select(UserModel).where(UserModel.email == normalized_email)
        )
