from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["environment"] == "test"


def test_openapi_schema_lists_versioned_routes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["openapi"].startswith("3.")
    assert "/health" in schema["paths"]
    assert "/api/v1/bugs" in schema["paths"]
    assert "/api/v1/auth/login" in schema["paths"]


def test_security_headers_present(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
