"""FR-20 admin-managed developer profiles."""

from fastapi.testclient import TestClient

from tests.conftest import Team

PROFILES = "/api/v1/admin/profiles"


def create(client: TestClient, team: Team, user_id: int, **fields: object):  # type: ignore[no-untyped-def]
    return client.post(PROFILES, json={"user_id": user_id, **fields}, headers=team.admin.headers)


def test_admin_creates_profile_with_normalised_tags(client: TestClient, team: Team) -> None:
    response = create(
        client,
        team,
        team.developer.id,
        skills=["Python", "python ", "SQL"],
        components=["Payments"],
        languages=["Python"],
        experience_level="Senior",
        availability="Available",
        max_workload=4,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["skills"] == ["python", "sql"]
    assert body["components"] == ["payments"]
    assert (body["experience_level"], body["max_workload"]) == ("Senior", 4)
    assert (body["resolved_count"], body["is_cold_start"], body["active"]) == (0, True, True)


def test_profile_rules(client: TestClient, team: Team) -> None:
    assert create(client, team, team.reporter.id).status_code == 422  # not a Developer
    assert create(client, team, 99999).status_code == 404
    assert create(client, team, team.developer.id).status_code == 201
    assert create(client, team, team.developer.id).status_code == 409
    assert create(client, team, team.developer2.id, max_workload=0).status_code == 422
    forbidden = client.post(
        PROFILES, json={"user_id": team.developer2.id}, headers=team.manager.headers
    )
    assert forbidden.status_code == 403


def test_update_deactivate_and_audit(client: TestClient, team: Team) -> None:
    profile = create(client, team, team.developer.id, skills=["python"]).json()
    url = f"{PROFILES}/{profile['id']}"
    response = client.patch(
        url,
        json={"skills": ["python", "react"], "availability": "Unavailable", "active": False},
        headers=team.admin.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["skills"], body["availability"], body["active"]) == (
        ["python", "react"],
        "Unavailable",
        False,
    )
    audit = client.get(f"{url}/audit", headers=team.admin.headers).json()
    changes = {a["field"]: (a["old_value"], a["new_value"]) for a in audit if a["field"]}
    assert changes["skills"] == ("python", "python, react")
    assert changes["active"] == ("True", "False")
    assert audit[0]["action"] == "profile_created"


def test_list_filters(client: TestClient, team: Team) -> None:
    create(client, team, team.developer.id)
    second = create(client, team, team.developer2.id).json()
    client.patch(f"{PROFILES}/{second['id']}", json={"active": False}, headers=team.admin.headers)
    active = client.get(PROFILES, params={"active": True}, headers=team.admin.headers).json()
    assert [p["user"]["id"] for p in active] == [team.developer.id]
    cold = client.get(PROFILES, params={"cold_start": True}, headers=team.admin.headers).json()
    assert len(cold) == 2
    assert client.get(f"{PROFILES}/99999", headers=team.admin.headers).status_code == 404
