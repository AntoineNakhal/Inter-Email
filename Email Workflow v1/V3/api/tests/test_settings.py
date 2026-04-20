from fastapi.testclient import TestClient

from api.app.main import create_app


def test_settings_endpoint_returns_runtime_shape() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    payload = response.json()
    assert "environment" in payload
    assert "ai_default_provider" in payload
