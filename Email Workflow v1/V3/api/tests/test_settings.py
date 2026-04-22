from fastapi.testclient import TestClient

from api.app.main import create_app


def test_settings_endpoint_returns_runtime_shape() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    payload = response.json()
    assert "environment" in payload
    assert "ai_default_provider" in payload
    assert "ai_mode" in payload
    assert "local_ai_force_all_threads" in payload


def test_settings_endpoint_updates_runtime_ai_mode() -> None:
    client = TestClient(create_app())
    original = client.get("/api/v1/settings")
    assert original.status_code == 200
    original_payload = original.json()

    update_payload = {
        "ai_mode": "local",
        "local_ai_force_all_threads": True,
        "local_ai_model": "llama3.1:8b",
        "local_ai_agent_prompt": "You are my local email workflow agent.",
    }
    response = client.put("/api/v1/settings", json=update_payload)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_mode"] == "local"
    assert payload["local_ai_force_all_threads"] is True
    assert payload["local_ai_model"] == "llama3.1:8b"

    restore_payload = {
        "ai_mode": original_payload["ai_mode"],
        "local_ai_force_all_threads": original_payload["local_ai_force_all_threads"],
        "local_ai_model": original_payload["local_ai_model"],
        "local_ai_agent_prompt": original_payload["local_ai_agent_prompt"],
    }
    restore_response = client.put("/api/v1/settings", json=restore_payload)
    assert restore_response.status_code == 200
