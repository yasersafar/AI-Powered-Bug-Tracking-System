"""FR-09 comments: flat, chronological, author + date."""

from fastapi.testclient import TestClient

from tests.conftest import Factory, Team


def test_comments_are_chronological_with_author(
    client: TestClient, team: Team, factory: Factory
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    url = f"/api/v1/bugs/{bug['id']}/comments"
    for actor, body in (
        (team.reporter, "First"),
        (team.developer, "Second"),
        (team.manager, "Third"),
    ):
        response = client.post(url, json={"body": body}, headers=actor.headers)
        assert response.status_code == 201
    comments = client.get(url, headers=team.developer.headers).json()
    assert [c["body"] for c in comments] == ["First", "Second", "Third"]
    assert [c["author"]["id"] for c in comments] == [
        team.reporter.id,
        team.developer.id,
        team.manager.id,
    ]
    assert all(c["created_at"] for c in comments)


def test_comment_validation(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    url = f"/api/v1/bugs/{bug['id']}/comments"
    assert client.post(url, json={"body": "   "}, headers=team.reporter.headers).status_code == 422
    assert (
        client.post(url, json={"body": "x" * 10001}, headers=team.reporter.headers).status_code
        == 422
    )


def test_outsider_cannot_comment(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = client.post(
        f"/api/v1/bugs/{bug['id']}/comments", json={"body": "hi"}, headers=team.outsider.headers
    )
    assert response.status_code == 403
