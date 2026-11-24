"""FR-21 developer tracking and FR-22 cold-start bookkeeping driven by real bug events."""

from fastapi.testclient import TestClient

from tests.conftest import Factory, Team

B = "/api/v1/bugs"


def make_profile(client: TestClient, team: Team, user_id: int) -> int:
    response = client.post(
        "/api/v1/admin/profiles", json={"user_id": user_id}, headers=team.admin.headers
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def resolve_bug(
    client: TestClient,
    team: Team,
    factory: Factory,
    developer_headers: dict[str, str],
    developer_id: int,
) -> int:
    bug = factory.bug(team.project_id, team.reporter)
    client.post(
        f"{B}/{bug['id']}/assign", json={"assignee_id": developer_id}, headers=team.manager.headers
    )
    response = client.post(
        f"{B}/{bug['id']}/transitions", json={"to_status": "Resolved"}, headers=developer_headers
    )
    assert response.status_code == 200
    return int(bug["id"])


def stats(client: TestClient, team: Team, user_id: int) -> dict[str, object]:
    response = client.get(f"/api/v1/admin/developers/{user_id}/stats", headers=team.admin.headers)
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


def profile(client: TestClient, team: Team, profile_id: int) -> dict[str, object]:
    body: dict[str, object] = client.get(
        f"/api/v1/admin/profiles/{profile_id}", headers=team.admin.headers
    ).json()
    return body


def test_cold_start_flag_follows_resolutions(
    client: TestClient, team: Team, factory: Factory
) -> None:
    client.put(
        "/api/v1/admin/settings",
        json={"values": {"cold_start_threshold": 2}},
        headers=team.admin.headers,
    )
    pid = make_profile(client, team, team.developer.id)
    assert stats(client, team, team.developer.id)["alpha"] == 0.0  # alpha = 0: pure profile score

    first = resolve_bug(client, team, factory, team.developer.headers, team.developer.id)
    assert profile(client, team, pid)["is_cold_start"] is True
    assert stats(client, team, team.developer.id)["alpha"] == 0.5  # 0 < alpha < 1: blended

    resolve_bug(client, team, factory, team.developer.headers, team.developer.id)
    assert (
        profile(client, team, pid)["resolved_count"],
        profile(client, team, pid)["is_cold_start"],
    ) == (2, False)
    assert stats(client, team, team.developer.id)["alpha"] == 1.0  # alpha = 1: pure history

    # Verification fails -> resolution no longer counts -> back to cold start
    client.post(
        f"{B}/{first}/transitions", json={"to_status": "InProgress"}, headers=team.reporter.headers
    )
    assert (
        profile(client, team, pid)["resolved_count"],
        profile(client, team, pid)["is_cold_start"],
    ) == (1, True)

    # Lowering N via settings re-evaluates every profile immediately
    client.put(
        "/api/v1/admin/settings",
        json={"values": {"cold_start_threshold": 1}},
        headers=team.admin.headers,
    )
    assert profile(client, team, pid)["is_cold_start"] is False


def test_developer_stats(client: TestClient, team: Team, factory: Factory) -> None:
    make_profile(client, team, team.developer.id)
    resolve_bug(client, team, factory, team.developer.headers, team.developer.id)

    tossed = factory.bug(team.project_id, team.reporter)
    assign = f"{B}/{tossed['id']}/assign"
    client.post(assign, json={"assignee_id": team.developer.id}, headers=team.manager.headers)
    client.post(assign, json={"assignee_id": team.developer2.id}, headers=team.manager.headers)
    client.post(assign, json={"assignee_id": team.developer.id}, headers=team.manager.headers)

    dev = stats(client, team, team.developer.id)
    assert dev["bugs_resolved"] == 1
    assert isinstance(dev["average_resolution_hours"], float)
    assert dev["reassignment_count"] == 1
    assert dev["current_workload"] == 1
    assert dev["max_workload"] == 5

    dev2 = stats(client, team, team.developer2.id)
    assert (dev2["reassignment_count"], dev2["current_workload"], dev2["profile_id"]) == (
        1,
        0,
        None,
    )

    everyone = client.get("/api/v1/admin/developers/stats", headers=team.admin.headers).json()
    assert {s["user"]["id"] for s in everyone} == {team.developer.id, team.developer2.id}
    assert (
        client.get("/api/v1/admin/developers/99999/stats", headers=team.admin.headers).status_code
        == 404
    )


def test_closing_ends_assignment(client: TestClient, team: Team, factory: Factory) -> None:
    bug_id = resolve_bug(client, team, factory, team.developer.headers, team.developer.id)
    client.post(
        f"{B}/{bug_id}/transitions", json={"to_status": "Verified"}, headers=team.reporter.headers
    )
    client.post(
        f"{B}/{bug_id}/transitions", json={"to_status": "Closed"}, headers=team.manager.headers
    )
    assert stats(client, team, team.developer.id)["current_workload"] == 0


def test_profile_created_after_history_counts_past_resolutions(
    client: TestClient, team: Team, factory: Factory
) -> None:
    resolve_bug(client, team, factory, team.developer.headers, team.developer.id)
    pid = make_profile(client, team, team.developer.id)
    assert profile(client, team, pid)["resolved_count"] == 1
