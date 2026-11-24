"""FR-18 project management, FR-19 team membership, FR-03 project isolation."""

from fastapi.testclient import TestClient

from tests.conftest import Factory, Team

P = "/api/v1/projects"


def test_reporter_cannot_create_project(client: TestClient, factory: Factory) -> None:
    reporter = factory.user()
    response = client.post(P, json={"name": "P1"}, headers=reporter.headers)
    assert response.status_code == 403


def test_project_manager_creates_project_and_becomes_its_manager(
    client: TestClient, team: Team
) -> None:
    response = client.post(
        P, json={"name": "New", "description": "x"}, headers=team.manager.headers
    )
    assert response.status_code == 201
    assert response.json()["my_role"] == "ProjectManager"


def test_project_names_are_unique(client: TestClient, team: Team) -> None:
    response = client.post(P, json={"name": "Payments"}, headers=team.manager.headers)
    assert response.status_code == 409


def test_non_member_cannot_see_project(client: TestClient, team: Team) -> None:
    assert client.get(f"{P}/{team.project_id}", headers=team.outsider.headers).status_code == 403
    assert (
        client.get(f"{P}/{team.project_id}/members", headers=team.outsider.headers).status_code
        == 403
    )
    assert client.get(P, headers=team.outsider.headers).json() == []


def test_member_sees_only_own_projects(client: TestClient, team: Team, factory: Factory) -> None:
    other_pm = factory.user(name="olga", role=team.manager.user.role)
    factory.project(other_pm, "Hidden")
    names = [p["name"] for p in client.get(P, headers=team.developer.headers).json()]
    assert names == ["Payments"]


def test_admin_sees_all_projects(client: TestClient, team: Team, factory: Factory) -> None:
    other_pm = factory.user(name="olga", role=team.manager.user.role)
    factory.project(other_pm, "Hidden")
    projects = client.get(P, headers=team.admin.headers).json()
    assert sorted(p["name"] for p in projects) == ["Hidden", "Payments"]
    assert all(p["my_role"] is None for p in projects)


def test_missing_project_is_404(client: TestClient, team: Team) -> None:
    assert client.get(f"{P}/9999", headers=team.manager.headers).status_code == 404


def test_rename_is_audited(client: TestClient, team: Team) -> None:
    url = f"{P}/{team.project_id}"
    response = client.patch(url, json={"name": "Payments v2"}, headers=team.manager.headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Payments v2"
    audit = client.get(f"{url}/audit", headers=team.manager.headers).json()
    assert ("project_updated", "Payments", "Payments v2") in [
        (a["action"], a["old_value"], a["new_value"]) for a in audit
    ]


def test_developer_cannot_rename(client: TestClient, team: Team) -> None:
    response = client.patch(
        f"{P}/{team.project_id}", json={"name": "Mine"}, headers=team.developer.headers
    )
    assert response.status_code == 403


def test_archived_project_is_read_only(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    url = f"{P}/{team.project_id}"
    assert client.post(f"{url}/archive", headers=team.manager.headers).json()["is_archived"]

    new_bug = client.post(
        "/api/v1/bugs",
        json={
            "project_id": team.project_id,
            "title": "Another bug",
            "description": "This should not be accepted on an archived project.",
            "steps_to_reproduce": "1",
            "environment": "any",
        },
        headers=team.reporter.headers,
    )
    assert new_bug.status_code == 409
    assert new_bug.json()["code"] == "project_archived"
    comment = client.post(
        f"/api/v1/bugs/{bug['id']}/comments", json={"body": "hi"}, headers=team.reporter.headers
    )
    assert comment.status_code == 409
    assert client.patch(url, json={"name": "X1"}, headers=team.manager.headers).status_code == 409
    # still readable
    assert client.get(f"/api/v1/bugs/{bug['id']}", headers=team.reporter.headers).status_code == 200
    detail = client.get(f"/api/v1/bugs/{bug['id']}", headers=team.manager.headers).json()
    assert detail["allowed_transitions"] == []
    assert detail["can_edit"] is False


def test_archive_twice_conflicts_and_only_admin_unarchives(client: TestClient, team: Team) -> None:
    url = f"{P}/{team.project_id}"
    client.post(f"{url}/archive", headers=team.manager.headers)
    assert client.post(f"{url}/archive", headers=team.manager.headers).status_code == 409
    assert client.post(f"{url}/unarchive", headers=team.manager.headers).status_code == 403
    response = client.post(f"{url}/unarchive", headers=team.admin.headers)
    assert response.status_code == 200
    assert response.json()["is_archived"] is False


def test_add_member_by_email_and_audit(client: TestClient, team: Team) -> None:
    url = f"{P}/{team.project_id}/members"
    response = client.post(
        url, json={"email": "OSCAR@example.com", "role": "Developer"}, headers=team.manager.headers
    )
    assert response.status_code == 201
    assert response.json()["user"]["id"] == team.outsider.id
    assert client.get(f"{P}/{team.project_id}", headers=team.outsider.headers).status_code == 200
    audit = client.get(f"{P}/{team.project_id}/audit", headers=team.manager.headers).json()
    assert any(a["action"] == "member_added" and "Oscar" in a["new_value"] for a in audit)


def test_add_member_validation(client: TestClient, team: Team) -> None:
    url = f"{P}/{team.project_id}/members"
    both = {"user_id": team.outsider.id, "email": "oscar@example.com", "role": "Developer"}
    assert client.post(url, json=both, headers=team.manager.headers).status_code == 422
    dup = {"user_id": team.developer.id, "role": "Developer"}
    assert client.post(url, json=dup, headers=team.manager.headers).status_code == 409
    ghost = {"user_id": 99999, "role": "Developer"}
    assert client.post(url, json=ghost, headers=team.manager.headers).status_code == 404
    by_dev = {"user_id": team.outsider.id, "role": "Developer"}
    assert client.post(url, json=by_dev, headers=team.developer.headers).status_code == 403


def test_change_member_role(client: TestClient, team: Team) -> None:
    url = f"{P}/{team.project_id}/members/{team.reporter.id}"
    response = client.patch(url, json={"role": "Developer"}, headers=team.manager.headers)
    assert response.status_code == 200
    assert response.json()["role"] == "Developer"
    missing = client.patch(
        f"{P}/{team.project_id}/members/99999",
        json={"role": "Developer"},
        headers=team.manager.headers,
    )
    assert missing.status_code == 404


def test_last_manager_cannot_leave_or_be_demoted(client: TestClient, team: Team) -> None:
    url = f"{P}/{team.project_id}/members/{team.manager.id}"
    assert client.delete(url, headers=team.manager.headers).status_code == 409
    demote = client.patch(url, json={"role": "Developer"}, headers=team.manager.headers)
    assert demote.status_code == 409
    assert demote.json()["code"] == "last_manager"


def test_remove_member(client: TestClient, team: Team) -> None:
    url = f"{P}/{team.project_id}/members/{team.reporter.id}"
    assert client.delete(url, headers=team.manager.headers).status_code == 204
    assert client.get(f"{P}/{team.project_id}", headers=team.reporter.headers).status_code == 403


def test_member_with_active_bugs_cannot_be_removed(
    client: TestClient, team: Team, factory: Factory
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    client.post(
        f"/api/v1/bugs/{bug['id']}/assign",
        json={"assignee_id": team.developer.id},
        headers=team.manager.headers,
    )
    response = client.delete(
        f"{P}/{team.project_id}/members/{team.developer.id}", headers=team.manager.headers
    )
    assert response.status_code == 409
    assert response.json()["details"] == {"active_bugs": 1}


def test_project_audit_requires_manager(client: TestClient, team: Team) -> None:
    response = client.get(f"{P}/{team.project_id}/audit", headers=team.developer.headers)
    assert response.status_code == 403
