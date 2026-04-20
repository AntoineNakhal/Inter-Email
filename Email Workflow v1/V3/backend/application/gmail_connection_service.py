"""Gmail OAuth connection workflow service."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.domain.gmail import GmailConnectionStatus
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
    ) -> None:
        self.gmail_client = gmail_client
        self.state_store = state_store

    def get_status(self, connect_url: str | None = None) -> GmailConnectionStatus:
        return self.gmail_client.get_connection_status(connect_url=connect_url)

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
        return status
