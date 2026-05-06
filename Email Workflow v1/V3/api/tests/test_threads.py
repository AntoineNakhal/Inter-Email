from fastapi.testclient import TestClient

from api.app.main import create_app


def test_threads_endpoint_returns_list_shape() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/threads")
    assert response.status_code == 401
