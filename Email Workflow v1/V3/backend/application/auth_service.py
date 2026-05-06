"""Google auth + JWT session workflow."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.core.config import AppSettings
from backend.core.crypto import decrypt_text, encrypt_text, hash_token
from backend.core.jwt import decode_jwt, encode_jwt
from backend.domain.user import AuthenticatedUser, UserRole
from backend.persistence.repositories.user_repository import UserRepository
from backend.providers.gmail.client import GmailReadonlyClient


@dataclass(slots=True)
class AuthFlowSession:
    state: str
    code_verifier: str
    created_at: datetime


class AuthFlowStateStore:
    def __init__(self) -> None:
        self._states: dict[str, AuthFlowSession] = {}

    def create(self, code_verifier: str) -> str:
        state = secrets.token_urlsafe(24)
        self._states[state] = AuthFlowSession(
            state=state,
            code_verifier=code_verifier,
            created_at=datetime.now(timezone.utc),
        )
        self._purge_expired()
        return state

    def consume(self, state: str) -> AuthFlowSession | None:
        self._purge_expired()
        return self._states.pop(state, None)

    def _purge_expired(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        expired = [
            key
            for key, session in self._states.items()
            if session.created_at < cutoff
        ]
        for key in expired:
            self._states.pop(key, None)


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
        state_store: AuthFlowStateStore,
    ) -> None:
        self.settings = settings
        self.user_repository = user_repository
        self.state_store = state_store

    def build_login_url(self, redirect_uri: str) -> str:
        gmail_client = GmailReadonlyClient(self.settings)
        code_verifier = gmail_client.generate_code_verifier()
        state = self.state_store.create(code_verifier)
        return gmail_client.build_authorization_url(
            redirect_uri=redirect_uri,
            state=state,
            code_verifier=code_verifier,
        )

    def finalize_google_login(
        self,
        *,
        redirect_uri: str,
        state: str,
        code: str,
    ) -> AuthSessionResult:
        auth_session = self.state_store.consume(state)
        if auth_session is None:
            raise ValueError("The Google sign-in session expired. Start again.")

        captured_credentials: dict[str, str] = {}
        gmail_client = GmailReadonlyClient(
            self.settings,
            persist_credentials=lambda payload: captured_credentials.__setitem__(
                "value",
                payload,
            ),
        )
        credentials_json = gmail_client.exchange_code_for_token(
            redirect_uri=redirect_uri,
            state=state,
            code=code,
            code_verifier=auth_session.code_verifier,
        )
        email = (gmail_client.get_profile_email() or "").strip().lower()
        if not email:
            raise RuntimeError("Google sign-in did not return an email address.")
        if email not in self.settings.parsed_auth_allowed_emails:
            raise PermissionError(f"{email} is not allowed to access this app.")

        role = (
            UserRole.ADMIN
            if email in self.settings.parsed_auth_admin_emails
            else UserRole.USER
        )
        encrypted_credentials = encrypt_text(
            captured_credentials.get("value") or credentials_json,
            self.settings.auth_token_encryption_key,
        )
        user = self.user_repository.upsert_google_user(
            email=email,
            display_name=gmail_client.get_profile_name() or email.split("@")[0],
            role=role,
            google_subject=None,
            gmail_token_encrypted=encrypted_credentials,
        )
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

    def refresh_access_token(self, refresh_token: str) -> AuthSessionResult:
        session_model = self.user_repository.get_session(hash_token(refresh_token))
        if session_model is None or session_model.revoked_at is not None:
            raise ValueError("Refresh session is invalid.")
        if session_model.expires_at <= datetime.now(timezone.utc):
            raise ValueError("Refresh session expired.")
        user = self.user_repository.get_by_id(session_model.user_id)
        if user is None:
            raise ValueError("User no longer exists.")
        self._ensure_user_allowed(user)
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
        self._ensure_user_allowed(user)
        return user

    def decrypt_user_gmail_token(self, user: AuthenticatedUser) -> str:
        model = self.user_repository.get_model_by_id(user.id)
        if model is None or not model.gmail_token_encrypted:
            raise ValueError("Google account is not connected for this user.")
        return decrypt_text(
            model.gmail_token_encrypted,
            self.settings.auth_token_encryption_key,
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

    def _ensure_user_allowed(self, user: AuthenticatedUser) -> None:
        if user.email not in self.settings.parsed_auth_allowed_emails:
            raise PermissionError(f"{user.email} is no longer allowed.")
