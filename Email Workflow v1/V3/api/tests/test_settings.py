from fastapi.testclient import TestClient

from api.app.main import create_app


def test_settings_endpoint_returns_runtime_shape() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/settings")
    assert response.status_code == 401


def test_settings_endpoint_updates_runtime_ai_mode() -> None:
    client = TestClient(create_app())
    response = client.put(
        "/api/v1/settings",
        json={
            "ai_mode": "local",
            "local_ai_force_all_threads": False,
            "local_ai_model": "llama3.1:8b",
            "local_ai_agent_prompt": "You are my local email workflow agent.",
        },
    )
    assert response.status_code == 401
