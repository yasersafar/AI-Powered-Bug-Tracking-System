"""NFR-14: thresholds are changed at runtime by an Administrator, no redeploy."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services import settings_service
from tests.conftest import Team

URL = "/api/v1/admin/settings"


def values(client: TestClient, team: Team) -> dict[str, float]:
    return {s["key"]: s["value"] for s in client.get(URL, headers=team.admin.headers).json()}


def test_defaults_are_listed(client: TestClient, team: Team) -> None:
    current = values(client, team)
    assert current["cold_start_threshold"] == 10
    assert current["exploration_rate"] == 0.1
    assert set(current) == set(settings_service.SPECS)


def test_update_applies_immediately(client: TestClient, team: Team, db: Session) -> None:
    response = client.put(
        URL,
        json={"values": {"exploration_rate": 0.25, "duplicate_timeout_ms": 900}},
        headers=team.admin.headers,
    )
    assert response.status_code == 200
    row = next(s for s in response.json() if s["key"] == "exploration_rate")
    assert (row["value"], row["updated_by"]["id"]) == (0.25, team.admin.id)
    assert settings_service.get_value(db, "exploration_rate") == 0.25
    assert settings_service.get_value(db, "duplicate_timeout_ms") == 900


def test_invalid_values_rejected(client: TestClient, team: Team) -> None:
    for bad in (
        {"exploration_rate": 1.5},
        {"cold_start_threshold": 0},
        {"cold_start_threshold": 2.5},
        {"duplicate_min_score": 0.9, "duplicate_likely_threshold": 0.5},
    ):
        response = client.put(URL, json={"values": bad}, headers=team.admin.headers)
        assert response.status_code == 422, bad
    unknown = client.put(URL, json={"values": {"nope": 1}}, headers=team.admin.headers)
    assert unknown.json()["code"] == "unknown_setting"
    assert values(client, team)["exploration_rate"] == 0.1  # nothing partially applied


def test_only_admin(client: TestClient, team: Team) -> None:
    assert client.get(URL, headers=team.manager.headers).status_code == 403
    response = client.put(
        URL, json={"values": {"exploration_rate": 0.2}}, headers=team.manager.headers
    )
    assert response.status_code == 403
