"""FR-16 e-mail and FR-17 in-app/push notifications (transports replaced by recorders)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from tests.conftest import Factory, Outbox, Team

N = "/api/v1/notifications"


def assign(client: TestClient, team: Team, bug_id: object, developer_id: int):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/bugs/{bug_id}/assign",
        json={"assignee_id": developer_id},
        headers=team.manager.headers,
    )


def test_assignment_notifies_assignee_on_all_channels(
    client: TestClient, team: Team, factory: Factory, outbox: Outbox
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    assign(client, team, bug["id"], team.developer.id)

    to_dev = [m for m in outbox.push.sent if m.to_email == team.developer.user.email]
    assert len(to_dev) == 1
    assert to_dev[0].title.startswith(f"[Bug #{bug['id']}] Assigned to you")
    assert to_dev[0].topic == f"bugtracker-{team.developer.user.ntfy_topic}"
    assert to_dev[0].priority == 4
    assert [m.to_email for m in outbox.email.sent if "Assigned" in m.title] == [
        team.developer.user.email
    ]

    inbox = client.get(N, headers=team.developer.headers).json()
    assert inbox["total"] == 1
    item = inbox["items"][0]
    assert (item["kind"], item["bug_id"], item["push_status"], item["email_status"]) == (
        "assigned",
        bug["id"],
        "sent",
        "sent",
    )
    # The reporter hears that work started; the PM (the actor) gets nothing.
    reporter_inbox = client.get(N, headers=team.reporter.headers).json()["items"]
    assert [n["kind"] for n in reporter_inbox] == ["status_changed"]
    assert client.get(N, headers=team.manager.headers).json()["total"] == 0


def test_status_change_notifies_reporter_and_assignee_not_actor(
    client: TestClient, team: Team, factory: Factory, outbox: Outbox
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    assign(client, team, bug["id"], team.developer.id)
    outbox.email.sent.clear()
    client.post(
        f"/api/v1/bugs/{bug['id']}/transitions",
        json={"to_status": "Resolved"},
        headers=team.developer.headers,
    )
    assert [m.to_email for m in outbox.email.sent] == [team.reporter.user.email]
    assert "InProgress → Resolved" in outbox.email.sent[0].title


def test_critical_severity_alerts_managers(
    client: TestClient, team: Team, factory: Factory, outbox: Outbox
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    client.post(
        f"/api/v1/bugs/{bug['id']}/severity",
        json={"severity": "Critical"},
        headers=team.developer.headers,
    )
    critical = [m for m in outbox.push.sent if "CRITICAL" in m.title]
    assert [m.to_email for m in critical] == [team.manager.user.email]
    assert critical[0].priority == 5
    # Setting Critical again does not alert twice
    client.post(
        f"/api/v1/bugs/{bug['id']}/severity",
        json={"severity": "Critical"},
        headers=team.manager.headers,
    )
    assert len([m for m in outbox.push.sent if "CRITICAL" in m.title]) == 1


def test_preferences_are_respected(
    client: TestClient, team: Team, factory: Factory, outbox: Outbox
) -> None:
    client.patch(
        "/api/v1/users/me",
        json={"email_notifications": False, "push_notifications": False},
        headers=team.developer.headers,
    )
    bug = factory.bug(team.project_id, team.reporter)
    assign(client, team, bug["id"], team.developer.id)
    assert not [
        m for m in outbox.push.sent + outbox.email.sent if m.to_email == team.developer.user.email
    ]
    item = client.get(N, headers=team.developer.headers).json()["items"][0]
    assert (item["push_status"], item["email_status"]) == (
        "skipped",
        "skipped",
    )  # in-app still there


def test_delivery_failure_never_breaks_the_request(
    client: TestClient, team: Team, factory: Factory, outbox: Outbox
) -> None:
    outbox.push.fail = outbox.email.fail = True
    bug = factory.bug(team.project_id, team.reporter)
    response = assign(client, team, bug["id"], team.developer.id)
    assert response.status_code == 200
    item = client.get(N, headers=team.developer.headers).json()["items"][0]
    assert (item["push_status"], item["email_status"]) == ("failed", "failed")


def test_read_state_api(client: TestClient, team: Team, factory: Factory, db: Session) -> None:
    for _ in range(3):
        bug = factory.bug(team.project_id, team.reporter)
        assign(client, team, bug["id"], team.developer.id)
    h = team.developer.headers
    assert client.get(f"{N}/unread-count", headers=h).json() == {"unread": 3}
    first = client.get(N, headers=h).json()["items"][0]["id"]
    assert client.post(f"{N}/{first}/read", headers=h).json() == {"updated": 1}
    assert client.post(f"{N}/{first}/read", headers=h).json() == {"updated": 0}  # idempotent
    assert client.get(N, params={"unread_only": True}, headers=h).json()["total"] == 2
    assert client.post(f"{N}/read-all", headers=h).json() == {"updated": 2}
    assert client.get(f"{N}/unread-count", headers=h).json() == {"unread": 0}
    # someone else's notification is invisible
    assert client.post(f"{N}/{first}/read", headers=team.reporter.headers).status_code == 404


def test_subscription_info(client: TestClient, team: Team, db: Session) -> None:
    body = client.get(f"{N}/subscription", headers=team.developer.headers).json()
    user = db.get(User, team.developer.id)
    assert user is not None
    assert body["topic"] == f"bugtracker-{user.ntfy_topic}"
    assert body["subscribe_url"] == f"{body['server_url']}/{body['topic']}"
