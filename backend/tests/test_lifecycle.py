"""FR-06 status lifecycle: valid transitions per role, 409 for invalid ones, assignment rules."""

import pytest
from fastapi.testclient import TestClient

from app.models import BugStatus
from app.services.lifecycle import TRANSITIONS, valid_targets
from tests.conftest import Factory, Team

B = "/api/v1/bugs"


def move(client: TestClient, bug_id: object, headers: dict[str, str], to: str, **extra: object):  # type: ignore[no-untyped-def]
    return client.post(
        f"{B}/{bug_id}/transitions", json={"to_status": to, **extra}, headers=headers
    )


def test_state_machine_matches_specification() -> None:
    assert set(TRANSITIONS) == {
        (BugStatus.OPEN, BugStatus.IN_PROGRESS),
        (BugStatus.IN_PROGRESS, BugStatus.RESOLVED),
        (BugStatus.RESOLVED, BugStatus.VERIFIED),
        (BugStatus.RESOLVED, BugStatus.IN_PROGRESS),
        (BugStatus.VERIFIED, BugStatus.CLOSED),
        (BugStatus.OPEN, BugStatus.CLOSED),
    }
    assert valid_targets(BugStatus.CLOSED) == []


def test_full_happy_path_with_audit(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    bug_id = bug["id"]

    assigned = client.post(
        f"{B}/{bug_id}/assign",
        json={"assignee_id": team.developer.id},
        headers=team.manager.headers,
    )
    assert assigned.json()["status"] == "InProgress"  # PM on assign: Open -> InProgress
    resolved = move(client, bug_id, team.developer.headers, "Resolved")
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None
    assert move(client, bug_id, team.reporter.headers, "Verified").status_code == 200
    closed = move(client, bug_id, team.manager.headers, "Closed")
    assert closed.status_code == 200
    assert (closed.json()["close_reason"], closed.json()["allowed_transitions"]) == ("fixed", [])

    audit = client.get(f"{B}/{bug_id}/audit", headers=team.reporter.headers).json()
    statuses = [(a["old_value"], a["new_value"]) for a in audit if a["action"] == "status_changed"]
    assert statuses == [
        ("Open", "InProgress"),
        ("InProgress", "Resolved"),
        ("Resolved", "Verified"),
        ("Verified", "Closed"),
    ]
    assignment = next(a for a in audit if a["action"] == "assigned")
    assert assignment["new_value"] == f"Dana (#{team.developer.id})"


def test_failed_verification_reopens(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    client.post(
        f"{B}/{bug['id']}/assign",
        json={"assignee_id": team.developer.id},
        headers=team.manager.headers,
    )
    move(client, bug["id"], team.developer.headers, "Resolved")
    reopened = move(client, bug["id"], team.reporter.headers, "InProgress")
    assert reopened.status_code == 200
    assert reopened.json()["resolved_at"] is None


@pytest.mark.parametrize(
    "target",
    ["Resolved", "Verified", "Open"],
)
def test_invalid_transitions_from_open_return_409(
    client: TestClient, team: Team, factory: Factory, target: str
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = move(client, bug["id"], team.admin.headers, target)
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "invalid_transition"
    assert set(body["details"]["valid_targets"]) == {"InProgress", "Closed"}


def test_closed_is_terminal(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    move(client, bug["id"], team.manager.headers, "Closed", close_reason="invalid")
    for target in ("Open", "InProgress", "Resolved", "Verified"):
        assert move(client, bug["id"], team.admin.headers, target).status_code == 409
    edit = client.patch(
        f"{B}/{bug['id']}", json={"title": "Changed after close"}, headers=team.manager.headers
    )
    assert edit.status_code == 409


def test_wrong_role_gets_403(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    # Only the PM can close an Open bug
    assert (
        move(
            client, bug["id"], team.developer.headers, "Closed", close_reason="invalid"
        ).status_code
        == 403
    )
    client.post(
        f"{B}/{bug['id']}/assign",
        json={"assignee_id": team.developer.id},
        headers=team.manager.headers,
    )
    # Only the assigned developer resolves
    assert move(client, bug["id"], team.developer2.headers, "Resolved").status_code == 403
    assert move(client, bug["id"], team.manager.headers, "Resolved").status_code == 403
    move(client, bug["id"], team.developer.headers, "Resolved")
    # Developers do not verify their own fix
    assert move(client, bug["id"], team.developer.headers, "Verified").status_code == 403
    move(client, bug["id"], team.reporter.headers, "Verified")
    # Only the PM closes
    assert move(client, bug["id"], team.reporter.headers, "Closed").status_code == 403


def test_close_open_bug_requires_reason(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = move(client, bug["id"], team.manager.headers, "Closed")
    assert response.status_code == 422


def test_close_reason_rejected_on_other_transitions(
    client: TestClient, team: Team, factory: Factory
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    client.post(
        f"{B}/{bug['id']}/assign",
        json={"assignee_id": team.developer.id},
        headers=team.manager.headers,
    )
    response = move(client, bug["id"], team.developer.headers, "Resolved", close_reason="invalid")
    assert response.status_code == 422


def test_close_as_duplicate_links_original(
    client: TestClient, team: Team, factory: Factory
) -> None:
    original = factory.bug(team.project_id, team.reporter)
    duplicate = factory.bug(team.project_id, team.reporter, title="Editor crash when saving")
    response = move(
        client,
        duplicate["id"],
        team.manager.headers,
        "Closed",
        close_reason="duplicate",
        duplicate_of_id=original["id"],
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["close_reason"], body["duplicate_of_id"]) == (
        "Closed",
        "duplicate",
        original["id"],
    )


def test_duplicate_must_be_in_same_project(
    client: TestClient, team: Team, factory: Factory
) -> None:
    other_project = factory.project(team.manager, "Other")
    foreign = factory.bug(other_project, team.manager)
    bug = factory.bug(team.project_id, team.reporter)
    for target in (foreign["id"], bug["id"], 999999):
        response = move(
            client,
            bug["id"],
            team.manager.headers,
            "Closed",
            close_reason="duplicate",
            duplicate_of_id=target,
        )
        assert response.status_code == 422
    missing_target = move(
        client, bug["id"], team.manager.headers, "Closed", close_reason="duplicate"
    )
    assert missing_target.status_code == 422


def test_start_work_requires_assignee(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = move(client, bug["id"], team.manager.headers, "InProgress")
    assert response.status_code == 409
    assert response.json()["code"] == "bug_unassigned"


def test_assignment_rules(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    url = f"{B}/{bug['id']}/assign"
    assert (
        client.post(
            url, json={"assignee_id": team.developer.id}, headers=team.developer.headers
        ).status_code
        == 403
    )
    for invalid in (team.reporter.id, team.outsider.id, 99999):
        response = client.post(url, json={"assignee_id": invalid}, headers=team.manager.headers)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_assignee"

    client.post(url, json={"assignee_id": team.developer.id}, headers=team.manager.headers)
    again = client.post(url, json={"assignee_id": team.developer.id}, headers=team.manager.headers)
    assert again.status_code == 200
    reassigned = client.post(
        url, json={"assignee_id": team.developer2.id}, headers=team.manager.headers
    )
    assert reassigned.json()["assignee"]["id"] == team.developer2.id
    audit = client.get(f"{B}/{bug['id']}/audit", headers=team.manager.headers).json()
    assert [a["action"] for a in audit if a["field"] == "assignee"] == ["assigned", "reassigned"]

    move(client, bug["id"], team.developer2.headers, "Resolved")
    late = client.post(url, json={"assignee_id": team.developer.id}, headers=team.manager.headers)
    assert late.status_code == 409


def test_admin_can_perform_any_valid_transition(
    client: TestClient, team: Team, factory: Factory
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = move(client, bug["id"], team.admin.headers, "Closed", close_reason="invalid")
    assert response.status_code == 200
