"""Email account connection service.

Orchestrates connecting and disconnecting email accounts for all supported
providers (Gmail, Outlook, iCloud, IMAP). Credentials are Fernet-encrypted
before being written to the database.

OAuth state for Gmail and Outlook is kept in an in-memory store with a 15-
minute TTL — same pattern as the existing GmailConnectionStateStore.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.core.config import AppSettings
from backend.core.crypto import decrypt_text, encrypt_text
from backend.persistence.repositories.email_account_repository import (
    EmailAccountRecord,
    EmailAccountRepository,
)
from backend.providers.gmail.client import GmailReadonlyClient
from backend.providers.imap.client import ImapClient


# ------------------------------------------------------------------ #
# In-memory OAuth state store (shared between Gmail + Outlook flows)   #
# ------------------------------------------------------------------ #

@dataclass(slots=True)
class OAuthFlowState:
    state: str
    provider: str           # 'gmail' | 'outlook'
    user_id: int
    code_verifier: str      # used by Gmail PKCE; empty string for Outlook
    extra: dict             # Outlook stores the MSAL auth_code_flow dict here
    created_at: datetime


class OAuthStateStore:
    def __init__(self) -> None:
        self._states: dict[str, OAuthFlowState] = {}

    def create(
        self,
        *,
        provider: str,
        user_id: int,
        code_verifier: str = "",
        extra: dict | None = None,
        state: str | None = None,   # explicit key — used by Outlook so MSAL state matches
    ) -> str:
        self._purge_expired()
        key = state or secrets.token_urlsafe(24)
        self._states[key] = OAuthFlowState(
            state=key,
            provider=provider,
            user_id=user_id,
            code_verifier=code_verifier,
            extra=extra or {},
            created_at=datetime.now(timezone.utc),
        )
        return key

    def consume(self, state: str) -> OAuthFlowState | None:
        self._purge_expired()
        return self._states.pop(state, None)

    def _purge_expired(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        expired = [k for k, v in self._states.items() if v.created_at < cutoff]
        for k in expired:
            self._states.pop(k, None)


# ------------------------------------------------------------------ #
# Service                                                               #
# ------------------------------------------------------------------ #

class EmailAccountService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        session: Session,
        state_store: OAuthStateStore,
    ) -> None:
        self.settings = settings
        self.session = session
        self.state_store = state_store
        self._repo = EmailAccountRepository(session)

    # ------------------------------------------------------------------ #
    # Read                                                                 #
    # ------------------------------------------------------------------ #

    def list_accounts(self, user_id: int) -> list[EmailAccountRecord]:
        return self._repo.list_for_user(user_id)

    # ------------------------------------------------------------------ #
    # Gmail OAuth flow                                                     #
    # ------------------------------------------------------------------ #

    def build_gmail_connect_url(self, user_id: int, redirect_uri: str) -> str:
        gmail_client = GmailReadonlyClient(self.settings)
        code_verifier = gmail_client.generate_code_verifier()
        state = self.state_store.create(
            provider="gmail",
            user_id=user_id,
            code_verifier=code_verifier,
        )
        return gmail_client.build_authorization_url(
            redirect_uri=redirect_uri,
            state=state,
            code_verifier=code_verifier,
        )

    def finalize_gmail_connection(
        self,
        *,
        user_id: int,
        state: str,
        code: str,
        redirect_uri: str,
    ) -> EmailAccountRecord:
        flow = self.state_store.consume(state)
        if flow is None or flow.provider != "gmail" or flow.user_id != user_id:
            raise ValueError("Gmail OAuth session expired or invalid. Please try again.")

        captured: dict[str, str] = {}
        gmail_client = GmailReadonlyClient(
            self.settings,
            persist_credentials=lambda payload: captured.__setitem__("value", payload),
        )
        credentials_json = gmail_client.exchange_code_for_token(
            redirect_uri=redirect_uri,
            state=state,
            code=code,
            code_verifier=flow.code_verifier,
        )
        email = (gmail_client.get_profile_email() or "").strip().lower()
        if not email:
            raise RuntimeError("Google did not return an email address.")

        display_name = gmail_client.get_profile_name()
        raw_creds = captured.get("value") or credentials_json
        return self._upsert_account(
            user_id=user_id,
            provider="gmail",
            email_address=email,
            display_name=display_name,
            raw_credentials=raw_creds,
        )

    # ------------------------------------------------------------------ #
    # Outlook OAuth flow                                                   #
    # ------------------------------------------------------------------ #

    def build_outlook_connect_url(self, user_id: int, redirect_uri: str) -> tuple[str, str]:
        """Returns (authorization_url, state). The MSAL flow is stored in state_store."""
        from backend.providers.outlook.client import OutlookClient

        client = OutlookClient(
            client_id=self.settings.outlook_client_id,
            client_secret=self.settings.outlook_client_secret,
            tenant_id=self.settings.outlook_tenant_id,
        )
        state_token = secrets.token_urlsafe(24)
        auth_uri, msal_flow = client.build_authorization_url(
            redirect_uri=redirect_uri,
            state=state_token,
        )
        # Use state_token as the store key so it matches what Microsoft echoes back.
        # msal_flow["state"] == state_token — MSAL embeds the state we passed in.
        self.state_store.create(
            provider="outlook",
            user_id=user_id,
            extra={"msal_flow": msal_flow},
            state=state_token,
        )
        return auth_uri, state_token

    def finalize_outlook_connection(
        self,
        *,
        user_id: int,
        state: str,
        auth_response: dict,
        redirect_uri: str,
    ) -> EmailAccountRecord:
        from backend.providers.outlook.client import OutlookClient

        flow = self.state_store.consume(state)
        if flow is None or flow.provider != "outlook" or flow.user_id != user_id:
            raise ValueError("Outlook OAuth session expired or invalid. Please try again.")

        client = OutlookClient(
            client_id=self.settings.outlook_client_id,
            client_secret=self.settings.outlook_client_secret,
            tenant_id=self.settings.outlook_tenant_id,
        )
        credentials_json = client.exchange_code_for_token(
            auth_code_flow=flow.extra["msal_flow"],
            auth_response=auth_response,
            redirect_uri=redirect_uri,
        )
        email, display_name = client.get_profile()
        if not email:
            raise RuntimeError("Microsoft did not return an email address.")

        return self._upsert_account(
            user_id=user_id,
            provider="outlook",
            email_address=email,
            display_name=display_name,
            raw_credentials=credentials_json,
        )

    # ------------------------------------------------------------------ #
    # iCloud IMAP connection                                               #
    # ------------------------------------------------------------------ #

    def connect_icloud(
        self,
        *,
        user_id: int,
        email_address: str,
        app_password: str,
    ) -> EmailAccountRecord:
        imap = ImapClient.for_icloud(
            username=email_address,
            app_password=app_password,
        )
        ok, error = imap.verify_connection()
        if not ok:
            raise ValueError(f"Could not connect to iCloud: {error}")

        return self._upsert_account(
            user_id=user_id,
            provider="icloud",
            email_address=imap.get_email_address(),
            display_name=None,
            raw_credentials=imap.credentials_json(),
        )

    # ------------------------------------------------------------------ #
    # Generic IMAP connection                                              #
    # ------------------------------------------------------------------ #

    def connect_imap(
        self,
        *,
        user_id: int,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
        display_name: str | None = None,
    ) -> EmailAccountRecord:
        imap = ImapClient.for_generic(
            host=host,
            port=port,
            username=username,
            password=password,
            use_ssl=use_ssl,
        )
        ok, error = imap.verify_connection()
        if not ok:
            raise ValueError(f"Could not connect via IMAP: {error}")

        return self._upsert_account(
            user_id=user_id,
            provider="imap",
            email_address=imap.get_email_address(),
            display_name=display_name,
            raw_credentials=imap.credentials_json(),
        )

    # ------------------------------------------------------------------ #
    # Disconnect                                                           #
    # ------------------------------------------------------------------ #

    def disconnect_account(self, *, account_id: int, user_id: int) -> bool:
        found = self._repo.deactivate(account_id, user_id)
        if found:
            self.session.commit()
        return found

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _upsert_account(
        self,
        *,
        user_id: int,
        provider: str,
        email_address: str,
        display_name: str | None,
        raw_credentials: str,
    ) -> EmailAccountRecord:
        """Create or update the email_account row for this user+email combo."""
        encrypted = encrypt_text(raw_credentials, self.settings.auth_token_encryption_key)

        # Check if this email is already connected for this user
        existing = self._find_existing(user_id, email_address)
        if existing:
            self._repo.update_credentials(existing.id, user_id, encrypted)
            self.session.commit()
            return self._repo.get_by_id(existing.id, user_id)  # type: ignore[return-value]

        record = self._repo.create(
            user_id=user_id,
            provider=provider,
            email_address=email_address,
            display_name=display_name,
            credentials_encrypted=encrypted,
        )
        self.session.commit()
        return record

    def _find_existing(self, user_id: int, email_address: str) -> EmailAccountRecord | None:
        all_accounts = self._repo.list_for_user(user_id)
        normalized = email_address.strip().lower()
        for acc in all_accounts:
            if acc.email_address == normalized:
                return acc
        return None
