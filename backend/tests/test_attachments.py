"""FR-14 attachments and NFR-07 path traversal / file type checks."""

import io
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.attachment_service import sanitize_filename, storage_path
from tests.conftest import Factory, Team


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")
        )

    header = (1).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0])
    pixel = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")
    )


PNG = _png()
WINDOWS_EXE = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 200


def upload(
    client: TestClient,
    bug_id: object,
    headers: dict[str, str],
    name: str,
    data: bytes,
    declared: str = "image/png",
):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/bugs/{bug_id}/attachments",
        files={"file": (name, io.BytesIO(data), declared)},
        headers=headers,
    )


def test_upload_list_download(
    client: TestClient, team: Team, factory: Factory, settings: Settings
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = upload(client, bug["id"], team.reporter.headers, "screen shot.png", PNG)
    assert response.status_code == 201, response.text
    meta = response.json()
    assert (meta["content_type"], meta["size_bytes"], meta["original_filename"]) == (
        "image/png",
        len(PNG),
        "screen shot.png",
    )
    stored = list(settings.attachment_dir.iterdir())
    assert len(stored) == 1 and len(stored[0].name) == 32  # random name, not the user's

    listed = client.get(
        f"/api/v1/bugs/{bug['id']}/attachments", headers=team.developer.headers
    ).json()
    assert [a["id"] for a in listed] == [meta["id"]]

    download = client.get(
        f"/api/v1/attachments/{meta['id']}/download", headers=team.developer.headers
    )
    assert download.status_code == 200
    assert download.content == PNG
    assert download.headers["content-type"] == "image/png"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"

    audit = client.get(f"/api/v1/bugs/{bug['id']}/audit", headers=team.reporter.headers).json()
    assert any(a["action"] == "attachment_added" for a in audit)


def test_download_requires_membership(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    attachment = upload(client, bug["id"], team.reporter.headers, "a.png", PNG).json()
    response = client.get(
        f"/api/v1/attachments/{attachment['id']}/download", headers=team.outsider.headers
    )
    assert response.status_code == 403
    assert (
        client.get("/api/v1/attachments/9999/download", headers=team.reporter.headers).status_code
        == 404
    )


def test_real_type_is_checked_not_the_declared_one(
    client: TestClient, team: Team, factory: Factory
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = upload(client, bug["id"], team.reporter.headers, "innocent.png", WINDOWS_EXE)
    assert response.status_code == 415
    assert response.json()["details"]["detected"] != "image/png"


def test_plain_text_logs_are_allowed(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = upload(
        client,
        bug["id"],
        team.reporter.headers,
        "app.log",
        b"2026-11-23 ERROR something failed\n",
        declared="application/octet-stream",
    )
    assert response.status_code == 201
    assert response.json()["content_type"] == "text/plain"


def test_empty_file_rejected(client: TestClient, team: Team, factory: Factory) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    assert upload(client, bug["id"], team.reporter.headers, "e.txt", b"").status_code == 422


def test_size_limit_enforced(settings: Settings, factory: Factory, team: Team) -> None:
    small = create_app(settings.model_copy(update={"attachment_max_bytes": 1024}))
    with TestClient(small) as client:
        bug = factory.bug(team.project_id, team.reporter)
        response = upload(client, bug["id"], team.reporter.headers, "big.txt", b"a" * 2048)
    small.state.engine.dispose()
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"
    assert not any(settings.attachment_dir.glob("*"))  # partial file cleaned up


def test_path_traversal_filename_is_neutralised(
    client: TestClient, team: Team, factory: Factory, settings: Settings
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    response = upload(client, bug["id"], team.reporter.headers, "../../../etc/passwd.png", PNG)
    assert response.status_code == 201
    assert response.json()["original_filename"] == "passwd.png"
    assert all(p.parent == settings.attachment_dir for p in settings.attachment_dir.rglob("*"))


def test_delete_permissions(
    client: TestClient, team: Team, factory: Factory, settings: Settings
) -> None:
    bug = factory.bug(team.project_id, team.reporter)
    attachment = upload(client, bug["id"], team.reporter.headers, "a.png", PNG).json()
    url = f"/api/v1/attachments/{attachment['id']}"
    assert client.delete(url, headers=team.developer.headers).status_code == 403
    assert client.delete(url, headers=team.reporter.headers).status_code == 204
    assert not any(settings.attachment_dir.iterdir())
    assert client.get(f"{url}/download", headers=team.reporter.headers).status_code == 404


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system.ini", "system.ini"),
        ("a\x00b.txt", "a_b.txt"),
        ("", "attachment"),
        ("...", "attachment"),
        (None, "attachment"),
        ('re<po>rt:"1".pdf', "re_po_rt__1_.pdf"),
        ("x" * 300 + ".png", "x" * 196 + ".png"),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize("key", ["../evil", "a" * 31, "A" * 32, "0123456789abcdef0123456789abcde/"])
def test_storage_path_rejects_bad_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        storage_path(tmp_path, key)


def test_storage_path_stays_inside_directory(tmp_path: Path) -> None:
    key = "0123456789abcdef0123456789abcdef"
    assert storage_path(tmp_path, key) == tmp_path.resolve() / key
