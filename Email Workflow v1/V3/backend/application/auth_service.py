"""Email/password auth + JWT session workflow.

Authentication (who you are) is now fully decoupled from email provider
connections (what mailboxes you read). Users register with an email address
and a password; they then connect Gmail / Outlook / iCloud / IMAP accounts
separately through the email_account_service.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt

from backend.core.config import AppSettings
from backend.core.jwt import decode_jwt, encode_jwt
from backend.core.crypto import hash_token
from backend.domain.user import AuthenticatedUser, UserRole
from backend.persistence.repositories.user_repository import UserRepository


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


@dataclass(slots=True)
class AuthSessionResult:
    user: AuthenticatedUser
    access_token: str
    refresh_token: str


class AuthService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        user_repository: UserRepository,
    ) -> None:
        self.settings = settings
        self.user_repository = user_repository

    # ------------------------------------------------------------------ #
    # Registration & login                                                 #
    # ------------------------------------------------------------------ #

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
    ) -> AuthSessionResult:
        """Create a new account and return a live session."""
        self._validate_password_strength(password)
        role = self._role_for_email(email)
        password_hash = _hash_password(password)
        user = self.user_repository.create_user(
            email=email,
            display_name=display_name,
            role=role,
            password_hash=password_hash,
        )
        return self._open_session(user)

    def login(self, *, email: str, password: str) -> AuthSessionResult:
        """Verify credentials and return a live session."""
        model = self.user_repository.get_model_by_email(email)
        # Verify against a dummy hash when user doesn't exist so timing is constant.
        candidate_hash = model.password_hash if model else "$2b$12$invalidhashpaddinginvalidhashpaddinginvalidhashpadding00"
        if not _verify_password(password, candidate_hash) or model is None:
            raise ValueError("Invalid email or password.")
        if not model.is_active:
            raise PermissionError("This account has been deactivated.")
        self.user_repository.update_last_login(model.id)
        self.user_repository.session.commit()
        user = self.user_repository._to_domain(model)
        return self._open_session(user)

    # ------------------------------------------------------------------ #
    # Session management                                                   #
    # ------------------------------------------------------------------ #

    def refresh_access_token(self, refresh_token: str) -> AuthSessionResult:
        session_model = self.user_repository.get_session(hash_token(refresh_token))
        if session_model is None or session_model.revoked_at is not None:
            raise ValueError("Refresh session is invalid.")
        if session_model.expires_at <= datetime.now(timezone.utc):
            raise ValueError("Refresh session expired.")
        user = self.user_repository.get_by_id(session_model.user_id)
        if user is None:
            raise ValueError("User no longer exists.")
        self.user_repository.touch_session(session_model)
        self.user_repository.session.commit()
        return AuthSessionResult(
            user=user,
            access_token=self._build_access_token(user),
            refresh_token=refresh_token,
        )

    def logout(self, refresh_token: str | None) -> None:
        if refresh_token:
            self.user_repository.revoke_session(hash_token(refresh_token))
            self.user_repository.session.commit()

    def get_user_from_access_token(self, token: str) -> AuthenticatedUser:
        claims = decode_jwt(token, self.settings.auth_jwt_secret)
        if claims.get("typ") != "access":
            raise ValueError("Unsupported token type.")
        user_id = int(claims.get("sub") or 0)
        user = self.user_repository.get_by_id(user_id)
        if user is None:
            raise ValueError("User not found.")
        return user

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _open_session(self, user: AuthenticatedUser) -> AuthSessionResult:
        refresh_token = secrets.token_urlsafe(48)
        self.user_repository.create_session(
            user_id=user.id,
            refresh_token_hash=hash_token(refresh_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=self.settings.auth_refresh_token_days),
        )
        self.user_repository.session.commit()
        return AuthSessionResult(
            user=user,
            access_token=self._build_access_token(user),
            refresh_token=refresh_token,
        )

    def _build_access_token(self, user: AuthenticatedUser) -> str:
        return encode_jwt(
            {
                "sub": user.id,
                "email": user.email,
                "role": user.role.value,
                "typ": "access",
            },
            self.settings.auth_jwt_secret,
            expires_in=timedelta(minutes=self.settings.auth_access_token_minutes),
        )

    def _role_for_email(self, email: str) -> UserRole:
        normalized = str(email or "").strip().lower()
        admin_emails = self.settings.parsed_auth_admin_emails
        if admin_emails and normalized in admin_emails:
            return UserRole.ADMIN
        return UserRole.USER

    @staticmethod
    def _validate_password_strength(password: str) -> None:
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
