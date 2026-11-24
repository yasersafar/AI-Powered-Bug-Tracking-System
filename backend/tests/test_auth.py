"""FR-01 registration, FR-02 authentication, NFR-04 bcrypt (adapted from the part2-auth tests)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import create_access_token
from app.main import create_app
from app.models import User
from tests.conftest import PASSWORD, Factory

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"


def register(client: TestClient, email: str = "dev@example.com", password: str = "Secret#123"):
    return client.post(
        REGISTER, json={"email": email, "full_name": "Dev One", "password": password}
    )


def test_register_creates_reporter_without_exposing_hash(client: TestClient) -> None:
    response = register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "dev@example.com"
    assert body["role"] == "Reporter"
    assert "password" not in str(body).lower()


def test_password_is_stored_as_salted_bcrypt_hash(client: TestClient, db: Session) -> None:
    register(client, "a@example.com", "Secret#123")
    register(client, "b@example.com", "Secret#123")
    hashes = db.scalars(select(User.password_hash).order_by(User.id)).all()
    assert all(h.startswith("$2b$") for h in hashes)
    assert hashes[0] != hashes[1]  # same password, different salt
    assert "Secret#123" not in hashes[0]


@pytest.mark.parametrize(
    ("password", "missing"),
    [
        ("Sh0rt!", "8 characters"),
        ("alllower1!", "uppercase"),
        ("NoDigits!!", "number"),
        ("NoSpecial12", "special"),
        ("A1!" + "x" * 80, "72"),
    ],
)
def test_password_policy(client: TestClient, password: str, missing: str) -> None:
    response = register(client, password=password)
    assert response.status_code == 422
    assert missing in str(response.json()["details"])


def test_register_duplicate_email_is_case_insensitive(client: TestClient) -> None:
    assert register(client, "Dev@Example.com").status_code == 201
    response = register(client, "dev@example.COM")
    assert response.status_code == 409
    assert response.json()["code"] == "email_taken"


def test_register_cannot_choose_a_role(client: TestClient) -> None:
    response = client.post(
        REGISTER,
        json={
            "email": "x@example.com",
            "full_name": "X",
            "password": "Secret#123",
            "role": "Administrator",
        },
    )
    assert response.status_code == 422


def test_register_rejects_invalid_email(client: TestClient) -> None:
    assert register(client, email="not-an-email").status_code == 422


def test_login_returns_eight_hour_token(client: TestClient, settings: Settings) -> None:
    register(client)
    response = client.post(LOGIN, data={"username": "dev@example.com", "password": "Secret#123"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 8 * 3600
    assert body["user"]["email"] == "dev@example.com"
    claims = jwt.decode(body["access_token"], settings.jwt_secret_key, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 8 * 3600


@pytest.mark.parametrize(
    ("email", "password"),
    [("dev@example.com", "Wrong#123"), ("nobody@example.com", "Secret#123")],
)
def test_login_rejects_bad_credentials(client: TestClient, email: str, password: str) -> None:
    register(client)
    response = client.post(LOGIN, data={"username": email, "password": password})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_inactive_user_cannot_log_in(client: TestClient, factory: Factory, db: Session) -> None:
    actor = factory.user()
    actor.user.is_active = False
    db.commit()
    response = client.post(LOGIN, data={"username": actor.user.email, "password": PASSWORD})
    assert response.status_code == 401


def test_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_expired_token_rejected(client: TestClient, factory: Factory, settings: Settings) -> None:
    actor = factory.user()
    nine_hours_ago = datetime.now(UTC) - timedelta(hours=9)
    token = create_access_token(actor.id, settings, now=nine_hours_ago)
    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_token_signed_with_other_key_rejected(
    client: TestClient, factory: Factory, settings: Settings
) -> None:
    actor = factory.user()
    forged = create_access_token(
        actor.id,
        settings.model_copy(update={"jwt_secret_key": "another-secret-key-of-sufficient-length"}),
    )
    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


@pytest.mark.parametrize("token", ["garbage", ""])
def test_malformed_token_rejected(client: TestClient, token: str) -> None:
    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_token_for_deleted_user_rejected(
    client: TestClient, factory: Factory, settings: Settings
) -> None:
    token = create_access_token(999_999, settings)
    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_login_is_rate_limited(settings: Settings) -> None:
    limited = create_app(settings.model_copy(update={"login_rate_limit_attempts": 3}))
    with TestClient(limited) as client:
        statuses = [
            client.post(
                LOGIN, data={"username": "x@example.com", "password": "Wrong#123"}
            ).status_code
            for _ in range(4)
        ]
    limited.state.engine.dispose()
    assert statuses == [401, 401, 401, 429]
