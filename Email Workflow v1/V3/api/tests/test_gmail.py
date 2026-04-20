from fastapi.testclient import TestClient

from api.app.main import create_app
from backend.application.gmail_connection_service import GmailConnectionService
from backend.domain.gmail import GmailConnectionStatus


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
