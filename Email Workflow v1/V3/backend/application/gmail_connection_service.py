"""Gmail OAuth connection workflow service."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.application.runtime_settings_service import RuntimeSettingsService
from backend.application.sync_progress_store import SyncProgressStore
from backend.domain.gmail import GmailConnectionStatus
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.gmail.client import GmailReadonlyClient


@dataclass(slots=True)
class GmailConnectionSession:
    state: str
    code_verifier: str
    created_at: datetime


class GmailConnectionStateStore:
    """Tiny in-memory state store for the local OAuth redirect flow."""

    def __init__(self) -> None:
        self._states: dict[str, GmailConnectionSession] = {}

    def create(self, code_verifier: str) -> str:
        self._purge_expired()
        state = secrets.token_urlsafe(24)
        self._states[state] = GmailConnectionSession(
            state=state,
            code_verifier=code_verifier,
            created_at=datetime.now(timezone.utc),
        )
        return state

    def consume(self, state: str) -> GmailConnectionSession | None:
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


class GmailConnectionService:
    """Owns the Gmail connect/status/callback workflow."""

    def __init__(
        self,
        gmail_client: GmailReadonlyClient,
        state_store: GmailConnectionStateStore,
        runtime_settings_service: RuntimeSettingsService | None = None,
        thread_repository: ThreadRepository | None = None,
        sync_repository: SyncRepository | None = None,
        progress_store: SyncProgressStore | None = None,
        session: Session | None = None,
    ) -> None:
        self.gmail_client = gmail_client
        self.state_store = state_store
        self.runtime_settings_service = runtime_settings_service
        self.thread_repository = thread_repository
        self.sync_repository = sync_repository
        self.progress_store = progress_store
        self.session = session

    def get_status(self, connect_url: str | None = None) -> GmailConnectionStatus:
        status = self.gmail_client.get_connection_status(connect_url=connect_url)
        self._synchronize_mailbox_scope(status)
        return status

    def build_connect_url(self, redirect_uri: str) -> str:
        code_verifier = self.gmail_client.generate_code_verifier()
        state = self.state_store.create(code_verifier=code_verifier)
        return self.gmail_client.build_authorization_url(
            redirect_uri=redirect_uri,
            state=state,
            code_verifier=code_verifier,
        )

    def finalize_connection(self, redirect_uri: str, state: str, code: str) -> GmailConnectionStatus:
        session = self.state_store.consume(state)
        if session is None:
            raise ValueError("The Gmail connection session expired. Start the connection again.")
        self.gmail_client.exchange_code_for_token(
            redirect_uri=redirect_uri,
            state=state,
            code=code,
            code_verifier=session.code_verifier,
        )
        status = self.gmail_client.get_connection_status()
        if not status.connected:
            raise RuntimeError(
                status.error_message
                or "The Gmail account could not be connected."
            )
        self._synchronize_mailbox_scope(status)
        return status

    def _synchronize_mailbox_scope(self, status: GmailConnectionStatus) -> None:
        if (
            self.runtime_settings_service is None
            or not status.connected
            or not status.email_address
        ):
            return

        next_mailbox_email = str(status.email_address or "").strip().lower()
        current_mailbox_email = (
            self.runtime_settings_service.get().gmail_mailbox_email.strip().lower()
        )
        if current_mailbox_email == next_mailbox_email:
            return

        if current_mailbox_email and current_mailbox_email != next_mailbox_email:
            if self.thread_repository is not None:
                self.thread_repository.clear_all()
            if self.sync_repository is not None:
                self.sync_repository.delete_all()
            if self.progress_store is not None:
                self.progress_store.clear()

        self.runtime_settings_service.set_gmail_mailbox_email(next_mailbox_email)
        if self.session is not None:
            self.session.commit()
