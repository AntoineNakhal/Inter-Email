from datetime import datetime

from fastapi.testclient import TestClient

from api.app.main import create_app
from backend.application.gmail_connection_service import GmailConnectionService
from backend.domain.gmail import GmailConnectionStatus
from backend.domain.runtime_settings import RuntimeSettings
from backend.providers.gmail.client import GmailReadonlyClient


def test_gmail_connection_status_returns_shape() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/gmail/connection")
    assert response.status_code == 200
    payload = response.json()
    assert "connected" in payload
    assert "credentials_configured" in payload
    assert "connect_url" in payload


class _StubStateStore:
    class _Session:
        code_verifier = "verifier"

    def create(self, code_verifier: str) -> str:
        return "state"

    def consume(self, state: str):
        return self._Session()


class _StubGmailClient:
    def generate_code_verifier(self) -> str:
        return "verifier"

    def build_authorization_url(
        self,
        redirect_uri: str,
        state: str,
        code_verifier: str,
    ) -> str:
        return "http://example.test/connect"

    def exchange_code_for_token(
        self,
        redirect_uri: str,
        state: str,
        code: str,
        code_verifier: str,
    ) -> None:
        return None

    def get_connection_status(self) -> GmailConnectionStatus:
        return GmailConnectionStatus(
            credentials_configured=True,
            connected=False,
            error_message="Token was not persisted.",
        )


def test_finalize_connection_raises_when_status_is_still_disconnected() -> None:
    service = GmailConnectionService(
        gmail_client=_StubGmailClient(),
        state_store=_StubStateStore(),
    )

    try:
        service.finalize_connection(
            redirect_uri="http://localhost:8000/api/v1/gmail/connect/callback",
            state="state",
            code="code",
        )
    except RuntimeError as exc:
        assert "Token was not persisted." in str(exc)
    else:
        raise AssertionError("Expected finalize_connection to raise for a disconnected status.")


class _ConnectedGmailClient(_StubGmailClient):
    def __init__(self, email_address: str) -> None:
        self.email_address = email_address

    def get_connection_status(self, connect_url: str | None = None) -> GmailConnectionStatus:
        return GmailConnectionStatus(
            credentials_configured=True,
            connected=True,
            email_address=self.email_address,
        )


class _StubRuntimeSettingsService:
    def __init__(self, gmail_mailbox_email: str) -> None:
        self.gmail_mailbox_email = gmail_mailbox_email

    def get(self) -> RuntimeSettings:
        return RuntimeSettings(gmail_mailbox_email=self.gmail_mailbox_email)

    def set_gmail_mailbox_email(self, gmail_mailbox_email: str) -> RuntimeSettings:
        self.gmail_mailbox_email = gmail_mailbox_email
        return self.get()


class _StubThreadRepository:
    def __init__(self) -> None:
        self.cleared = False

    def clear_all(self) -> None:
        self.cleared = True


class _StubSyncRepository:
    def __init__(self) -> None:
        self.cleared = False

    def delete_all(self) -> None:
        self.cleared = True


class _StubProgressStore:
    def __init__(self) -> None:
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


class _StubSession:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


def test_finalize_connection_clears_old_inbox_when_gmail_account_changes() -> None:
    runtime_settings_service = _StubRuntimeSettingsService(
        gmail_mailbox_email="first@example.com"
    )
    thread_repository = _StubThreadRepository()
    sync_repository = _StubSyncRepository()
    progress_store = _StubProgressStore()
    session = _StubSession()
    service = GmailConnectionService(
        gmail_client=_ConnectedGmailClient("second@example.com"),
        state_store=_StubStateStore(),
        runtime_settings_service=runtime_settings_service,
        thread_repository=thread_repository,
        sync_repository=sync_repository,
        progress_store=progress_store,
        session=session,
    )

    status = service.finalize_connection(
        redirect_uri="http://localhost:8000/api/v1/gmail/connect/callback",
        state="state",
        code="code",
    )

    assert status.email_address == "second@example.com"
    assert runtime_settings_service.gmail_mailbox_email == "second@example.com"
    assert thread_repository.cleared is True
    assert sync_repository.cleared is True
    assert progress_store.cleared is True
    assert session.committed is True


def test_build_query_uses_custom_lookback_days() -> None:
    query = GmailReadonlyClient.build_query(
        source="received",
        now=datetime(2026, 4, 24, 12, 0, 0),
        lookback_days=30,
    )

    assert query.startswith("-in:sent after:")
    assert query.endswith("2026/03/25")


def test_build_query_clamps_invalid_lookback_days() -> None:
    query = GmailReadonlyClient.build_query(
        source="anywhere",
        now=datetime(2026, 4, 24, 12, 0, 0),
        lookback_days=0,
    )

    assert query == "in:anywhere after:2026/04/23"
