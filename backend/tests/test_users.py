"""FR-04 profile management and FR-03 user administration."""

from fastapi.testclient import TestClient

from app.models import UserRole
from tests.conftest import PASSWORD, Factory, Team

ME = "/api/v1/users/me"


def test_read_me_includes_private_ntfy_topic(client: TestClient, factory: Factory) -> None:
    actor = factory.user()
    body = client.get(ME, headers=actor.headers).json()
    assert body["email"] == actor.user.email
    assert len(body["ntfy_topic"]) >= 20


def test_update_own_name_and_notification_preferences(client: TestClient, factory: Factory) -> None:
    actor = factory.user()
    response = client.patch(
        ME,
        json={"full_name": "New Name", "email_notifications": False, "push_notifications": False},
        headers=actor.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["full_name"], body["email_notifications"], body["push_notifications"]) == (
        "New Name",
        False,
        False,
    )


def test_cannot_change_own_role_via_profile(client: TestClient, factory: Factory) -> None:
    actor = factory.user()
    response = client.patch(ME, json={"role": "Administrator"}, headers=actor.headers)
    assert response.status_code == 422


def test_change_password_revokes_old_tokens(client: TestClient, factory: Factory) -> None:
    actor = factory.user()
    response = client.post(
        f"{ME}/password",
        json={"current_password": PASSWORD, "new_password": "Brand#New1"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    new_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    assert client.get(ME, headers=actor.headers).status_code == 401
    assert client.get(ME, headers=new_headers).status_code == 200
    assert factory.login(actor.user.email, "Brand#New1")


def test_change_password_requires_current_password(client: TestClient, factory: Factory) -> None:
    actor = factory.user()
    response = client.post(
        f"{ME}/password",
        json={"current_password": "Wrong#123", "new_password": "Brand#New1"},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "wrong_password"


def test_change_password_enforces_policy(client: TestClient, factory: Factory) -> None:
    actor = factory.user()
    response = client.post(
        f"{ME}/password",
        json={"current_password": PASSWORD, "new_password": "weak"},
        headers=actor.headers,
    )
    assert response.status_code == 422


def test_project_manager_can_search_users(client: TestClient, team: Team) -> None:
    response = client.get("/api/v1/users", params={"q": "dana"}, headers=team.manager.headers)
    assert response.status_code == 200
    assert [u["full_name"] for u in response.json()["items"]] == ["Dana"]


def test_reporter_cannot_search_users(client: TestClient, team: Team) -> None:
    response = client.get("/api/v1/users", headers=team.reporter.headers)
    assert response.status_code == 403


def test_admin_changes_role_and_it_is_audited(client: TestClient, team: Team) -> None:
    url = f"/api/v1/users/{team.reporter.id}"
    response = client.patch(url, json={"role": "Developer"}, headers=team.admin.headers)
    assert response.status_code == 200
    assert response.json()["role"] == "Developer"
    audit = client.get(f"{url}/audit", headers=team.admin.headers).json()
    assert [(a["action"], a["old_value"], a["new_value"]) for a in audit] == [
        ("role_changed", "Reporter", "Developer")
    ]
    assert audit[0]["actor"]["id"] == team.admin.id


def test_non_admin_cannot_change_roles(client: TestClient, team: Team) -> None:
    response = client.patch(
        f"/api/v1/users/{team.reporter.id}",
        json={"role": UserRole.ADMINISTRATOR.value},
        headers=team.manager.headers,
    )
    assert response.status_code == 403


def test_admin_cannot_demote_self(client: TestClient, team: Team) -> None:
    response = client.patch(
        f"/api/v1/users/{team.admin.id}", json={"role": "Reporter"}, headers=team.admin.headers
    )
    assert response.status_code == 409


def test_deactivated_user_token_stops_working(client: TestClient, team: Team) -> None:
    response = client.patch(
        f"/api/v1/users/{team.developer.id}", json={"is_active": False}, headers=team.admin.headers
    )
    assert response.status_code == 200
    assert client.get(ME, headers=team.developer.headers).status_code == 401


def test_admin_update_unknown_user_404(client: TestClient, team: Team) -> None:
    response = client.patch(
        "/api/v1/users/99999", json={"role": "Developer"}, headers=team.admin.headers
    )
    assert response.status_code == 404
