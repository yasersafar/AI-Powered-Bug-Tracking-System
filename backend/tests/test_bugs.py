"""FR-05 submission, FR-07 search, FR-08 audit, FR-11 override, NFR-07 input validation."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import Factory, Team

B = "/api/v1/bugs"


def test_submit_bug_without_ai_is_unclassified(
    client: TestClient, team: Team, factory: Factory
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    assert bug["status"] == "Open"
    assert bug["severity"] == "Unclassified"
    assert bug["ai_status"] == "degraded"
    assert bug["reporter"]["id"] == team.reporter.id
    assert bug["components"] == ["editor"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("description", "too short"),
        ("title", "abc"),
        ("steps_to_reproduce", ""),
        ("environment", ""),
        ("environment", "line1\nline2"),
        ("title", "bad\x00title"),
    ],
)
def test_submission_validation(client: TestClient, team: Team, field: str, value: str) -> None:
    payload = {
        "project_id": team.project_id,
        "title": "Editor crashes on save",
        "description": "Saving a file larger than 2 MB closes the editor.",
        "steps_to_reproduce": "1. Save",
        "environment": "macOS",
        field: value,
    }
    response = client.post(B, json=payload, headers=team.reporter.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_outsider_cannot_submit_or_read(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    payload = {
        "project_id": team.project_id,
        "title": "Outsider bug",
        "description": "An outsider tries to post into a foreign project.",
        "steps_to_reproduce": "1",
        "environment": "x",
    }
    assert client.post(B, json=payload, headers=team.outsider.headers).status_code == 403
    for path in ("", "/audit", "/comments", "/attachments"):
        assert (
            client.get(f"{B}/{bug['id']}{path}", headers=team.outsider.headers).status_code == 403
        )
    listing = client.get(B, headers=team.outsider.headers).json()
    assert listing["total"] == 0
    scoped = client.get(B, params={"project_id": team.project_id}, headers=team.outsider.headers)
    assert scoped.status_code == 403


def test_missing_bug_is_404(client: TestClient, team: Team) -> None:
    assert client.get(f"{B}/424242", headers=team.reporter.headers).status_code == 404


def test_detail_reports_permissions(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    as_manager = client.get(f"{B}/{bug['id']}", headers=team.manager.headers).json()
    assert as_manager["can_assign"] is True
    assert set(as_manager["allowed_transitions"]) == {"InProgress", "Closed"}
    as_reporter = client.get(f"{B}/{bug['id']}", headers=team.reporter.headers).json()
    assert as_reporter["can_assign"] is False
    assert as_reporter["can_override_severity"] is False
    assert as_reporter["can_edit"] is True
    assert as_reporter["allowed_transitions"] == []


def test_edit_fields_is_audited(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = client.patch(
        f"{B}/{bug['id']}",
        json={"title": "Editor crashes when saving big files", "components": ["editor", "io"]},
        headers=team.reporter.headers,
    )
    assert response.status_code == 200
    audit = client.get(f"{B}/{bug['id']}/audit", headers=team.reporter.headers).json()
    changes = {
        a["field"]: (a["old_value"], a["new_value"])
        for a in audit
        if a["action"] == "field_changed"
    }
    assert changes["title"] == ("Editor crashes on save", "Editor crashes when saving big files")
    assert changes["components"] == ("editor", "editor, io")
    assert all(
        a["actor"]["id"] == team.reporter.id for a in audit if a["action"] == "field_changed"
    )
    assert all(a["created_at"].endswith(("Z", "+00:00")) for a in audit)


def test_unrelated_developer_cannot_edit(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = client.patch(
        f"{B}/{bug['id']}", json={"title": "Hijacked title"}, headers=team.developer.headers
    )
    assert response.status_code == 403


def test_severity_override_by_developer_is_audited(
    client: TestClient, team: Team, factory: Factory
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = client.post(
        f"{B}/{bug['id']}/severity", json={"severity": "Critical"}, headers=team.developer.headers
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["severity"], body["severity_overridden"]) == ("Critical", True)
    audit = client.get(f"{B}/{bug['id']}/audit", headers=team.developer.headers).json()
    entry = next(a for a in audit if a["action"] == "severity_overridden")
    assert (entry["old_value"], entry["new_value"], entry["actor"]["id"]) == (
        "Unclassified",
        "Critical",
        team.developer.id,
    )


def test_reporter_cannot_override_severity(
    client: TestClient, team: Team, factory: Factory
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = client.post(
        f"{B}/{bug['id']}/severity", json={"severity": "Low"}, headers=team.reporter.headers
    )
    assert response.status_code == 403


def test_cannot_override_to_unclassified(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = client.post(
        f"{B}/{bug['id']}/severity", json={"severity": "Unclassified"}, headers=team.manager.headers
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- search (FR-07)
@pytest.fixture
def corpus(client: TestClient, team: Team, factory: Factory) -> dict[str, int]:
    ids = {}
    ids["login"] = int(
        factory.bug(
            team.project_id,
            team.reporter,
            title="Login button does nothing",
            description="Clicking the login button on the start page has no effect at all.",
        )["id"]
    )
    ids["crash"] = int(
        factory.bug(
            team.project_id,
            team.reporter,
            title="Crash on export to PDF",
            description="Exporting a report to PDF crashes the application immediately.",
        )["id"]
    )
    ids["slow"] = int(
        factory.bug(
            team.project_id,
            team.developer,
            title="Search is very slow",
            description="Searching in large workspaces takes more than ten seconds to return.",
        )["id"]
    )
    client.post(
        f"{B}/{ids['crash']}/severity", json={"severity": "Critical"}, headers=team.manager.headers
    )
    client.post(
        f"{B}/{ids['slow']}/assign",
        json={"assignee_id": team.developer.id},
        headers=team.manager.headers,
    )
    return ids


def _ids(response) -> list[int]:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_keyword_search_uses_full_text(
    client: TestClient, team: Team, corpus: dict[str, int]
) -> None:
    h = team.manager.headers
    assert _ids(client.get(B, params={"q": "crashes"}, headers=h)) == [corpus["crash"]]  # stemming
    assert _ids(client.get(B, params={"q": "login"}, headers=h)) == [corpus["login"]]
    assert _ids(client.get(B, params={"q": '"login button" -export'}, headers=h)) == [
        corpus["login"]
    ]
    relevance = client.get(B, params={"q": "slow search", "sort": "relevance"}, headers=h)
    assert _ids(relevance)[0] == corpus["slow"]


def test_filters_combine(client: TestClient, team: Team, corpus: dict[str, int]) -> None:
    h = team.manager.headers
    assert _ids(client.get(B, params={"severity": "Critical"}, headers=h)) == [corpus["crash"]]
    assert _ids(client.get(B, params={"status": "InProgress"}, headers=h)) == [corpus["slow"]]
    assert _ids(client.get(B, params={"assignee_id": team.developer.id}, headers=h)) == [
        corpus["slow"]
    ]
    assert _ids(client.get(B, params={"reporter_id": team.developer.id}, headers=h)) == [
        corpus["slow"]
    ]
    both = client.get(
        B,
        params=[("status", "Open"), ("status", "InProgress"), ("severity", "Unclassified")],
        headers=h,
    )
    assert sorted(_ids(both)) == sorted([corpus["login"], corpus["slow"]])
    assert _ids(client.get(B, params={"sort": "severity_desc"}, headers=h))[0] == corpus["crash"]


def test_date_range_filter(client: TestClient, team: Team, corpus: dict[str, int]) -> None:
    h = team.manager.headers
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert _ids(client.get(B, params={"created_from": future}, headers=h)) == []
    assert (
        len(_ids(client.get(B, params={"created_from": past, "created_to": future}, headers=h)))
        == 3
    )
    assert _ids(client.get(B, params={"created_to": past}, headers=h)) == []


def test_pagination(client: TestClient, team: Team, corpus: dict[str, int]) -> None:
    h = team.manager.headers
    first = client.get(B, params={"page_size": 2, "sort": "created_asc"}, headers=h).json()
    second = client.get(
        B, params={"page_size": 2, "page": 2, "sort": "created_asc"}, headers=h
    ).json()
    assert first["total"] == second["total"] == 3
    assert [i["id"] for i in first["items"]] + [i["id"] for i in second["items"]] == [
        corpus["login"],
        corpus["crash"],
        corpus["slow"],
    ]
    assert client.get(B, params={"page_size": 500}, headers=h).status_code == 422


def test_search_is_safe_against_sql_injection(
    client: TestClient, team: Team, corpus: dict[str, int], db: Session
) -> None:
    payloads = ["'; DROP TABLE bug; --", "login' OR '1'='1", "\\x00 & | ! :* <->"]
    for q in payloads:
        response = client.get(B, params={"q": q}, headers=team.manager.headers)
        assert response.status_code in (200, 422)
    assert db.scalar(text("SELECT count(*) FROM bug")) == 3


def test_html_is_stored_verbatim_and_returned_as_json(
    client: TestClient, team: Team, factory: Factory
) -> None:
    script = "<script>alert('x')</script> appears when the description has HTML in it"
    bug = factory.bug(team.project_id, team.reporter, description=script)
    response = client.get(f"{B}/{bug['id']}", headers=team.reporter.headers)
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["description"] == script
