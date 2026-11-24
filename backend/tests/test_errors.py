from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import AppError


class _Payload(BaseModel):
    count: int


def _add_routes(app: FastAPI) -> None:
    @app.get("/_raise-app-error")
    def raise_app_error() -> None:
        raise AppError(409, "invalid_transition", "Cannot move Open to Verified", {"from": "Open"})

    @app.post("/_validate")
    def validate(payload: _Payload) -> _Payload:
        return payload

    @app.get("/_boom")
    def boom() -> None:
        raise RuntimeError("unexpected")


def test_app_error_uses_standard_format(app: FastAPI, client: TestClient) -> None:
    _add_routes(app)
    response = client.get("/_raise-app-error")
    assert response.status_code == 409
    assert response.json() == {
        "code": "invalid_transition",
        "message": "Cannot move Open to Verified",
        "details": {"from": "Open"},
    }


def test_unknown_route_returns_not_found_code(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_validation_error_format(app: FastAPI, client: TestClient) -> None:
    _add_routes(app)
    response = client.post("/_validate", json={"count": "not-a-number"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["details"][0]["loc"] == ["body", "count"]


def test_unhandled_error_hides_internals(app: FastAPI, client: TestClient) -> None:
    _add_routes(app)
    response = client.get("/_boom")
    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "Internal server error",
        "details": None,
    }
