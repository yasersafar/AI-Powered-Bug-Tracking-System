from app.core import security


def register_user(
    client,
    email="dev@example.com",
    password="secret123",
    role="developer",
    full_name="Dev One",
):
    return client.post(
        "/auth/register",
        json={
            "email": email,
            "full_name": full_name,
            "password": password,
            "role": role,
        },
    )


def login(client, email, password):
    return client.post(
        "/auth/login", data={"username": email, "password": password}
    )


def test_register_creates_user(client):
    resp = register_user(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "dev@example.com"
    assert body["role"] == "developer"
    assert "hashed_password" not in body  # the hash must never be returned


def test_register_duplicate_email_rejected(client):
    register_user(client)
    resp = register_user(client)
    assert resp.status_code == 400


def test_login_returns_token(client):
    register_user(client)
    resp = login(client, "dev@example.com", "secret123")
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert resp.json()["access_token"]


def test_login_wrong_password_rejected(client):
    register_user(client)
    resp = login(client, "dev@example.com", "wrongpass")
    assert resp.status_code == 401


def test_expired_token_rejected(client, monkeypatch):
    register_user(client)
    # Force a token that is already expired, then confirm it is refused.
    monkeypatch.setattr(security.settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    token = security.create_access_token(subject="1")
    monkeypatch.setattr(security.settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 480)
    resp = client.get("/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
