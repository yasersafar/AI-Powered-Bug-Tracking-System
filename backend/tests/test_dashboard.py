"""FR-15 project dashboard."""

from fastapi.testclient import TestClient

from tests.conftest import Factory, Team


def test_dashboard_figures(client: TestClient, team: Team, factory: Factory) -> None:
    b1 = factory.bug(team.project_id, team.reporter, components=["editor", "io"])
    factory.bug(team.project_id, team.reporter, components=["editor"])
    b3 = factory.bug(team.project_id, team.reporter, components=["auth"])
    client.post(
        f"/api/v1/bugs/{b3['id']}/severity",
        json={"severity": "Critical"},
        headers=team.manager.headers,
    )
    client.post(
        f"/api/v1/bugs/{b1['id']}/assign",
        json={"assignee_id": team.developer.id},
        headers=team.manager.headers,
    )
    client.post(
        f"/api/v1/bugs/{b1['id']}/transitions",
        json={"to_status": "Resolved"},
        headers=team.developer.headers,
    )

    response = client.get(
        f"/api/v1/projects/{team.project_id}/dashboard",
        params={"days": 7},
        headers=team.reporter.headers,
    )
    assert response.status_code == 200
    d = response.json()
    assert d["total_bugs"] == 3
    assert d["by_status"] == {"Open": 2, "InProgress": 0, "Resolved": 1, "Verified": 0, "Closed": 0}
    assert d["by_severity"]["Critical"] == 1 and d["by_severity"]["Unclassified"] == 2
    assert (d["open_bugs"], d["open_critical"]) == (2, 1)
    assert len(d["over_time"]) == 7
    assert d["over_time"][-1]["created"] == 3 and d["over_time"][-1]["resolved"] == 1
    assert d["average_resolution_hours"] is not None
    assert d["top_components"] == [
        {"component": "auth", "open_bugs": 1},
        {"component": "editor", "open_bugs": 1},
    ]


def test_dashboard_access_and_validation(client: TestClient, team: Team) -> None:
    url = f"/api/v1/projects/{team.project_id}/dashboard"
    assert client.get(url, headers=team.outsider.headers).status_code == 403
    assert client.get(url, params={"days": 3}, headers=team.manager.headers).status_code == 422
    empty = client.get(url, headers=team.manager.headers).json()
    assert (empty["total_bugs"], empty["average_resolution_hours"], len(empty["over_time"])) == (
        0,
        None,
        30,
    )
