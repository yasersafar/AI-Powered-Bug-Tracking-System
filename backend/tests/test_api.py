from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_bug_returns_unclassified_while_no_model():
    response = client.post("/bugs", json={"title": "Crash on save", "description": "Editor closes"})
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Crash on save"
    assert body["severity"] == "Unclassified"


def test_create_bug_rejects_empty_title():
    response = client.post("/bugs", json={"title": "", "description": "x"})
    assert response.status_code == 422
