"""Live delivery through the real self-hosted ntfy and SMTP (Mailpit) from docker-compose.

Opt-in: `make test-live` (or `pytest -m live`) with `make up` running. Uses the real
NtfyPushSender / SmtpEmailSender and reads the results back from ntfy and the Mailpit API.
"""

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.core.config import get_settings
from app.services.notification_service import NtfyPushSender, OutgoingMessage, SmtpEmailSender

pytestmark = pytest.mark.live

MAILPIT_API = "http://localhost:8025/api/v1"


def _message(topic: str, marker: str) -> OutgoingMessage:
    return OutgoingMessage(
        to_email="dana@example.com",
        to_name="Dana Developer",
        topic=topic,
        title=f"[Bug #1] Assigned to you ({marker})",
        body="Live delivery test",
        priority=4,
        tags=("bug",),
    )


def test_push_reaches_self_hosted_ntfy_and_is_access_controlled() -> None:
    settings = get_settings()
    assert settings.ntfy_publish_token, "run `make env` and `make up` first"
    marker = secrets.token_hex(4)
    topic = f"{settings.ntfy_topic_prefix}-live-{marker}"

    NtfyPushSender(settings).send(_message(topic, marker))

    url = f"{settings.ntfy_publish_url}/{topic}/json?poll=1"
    with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 (local test server)
        events = [json.loads(line) for line in response.read().decode().splitlines() if line]
    assert [e["title"] for e in events if e.get("event") == "message"] == [
        f"[Bug #1] Assigned to you ({marker})"
    ]

    # Anonymous clients may read but never publish (deny-all + write-only publisher).
    anonymous = urllib.request.Request(  # noqa: S310
        f"{settings.ntfy_publish_url}/{topic}", data=b"spoof", method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as rejected:
        urllib.request.urlopen(anonymous, timeout=5)  # noqa: S310
    assert rejected.value.code == 403


def test_email_arrives_in_mailpit() -> None:
    settings = get_settings()
    marker = secrets.token_hex(4)
    SmtpEmailSender(settings).send(_message("unused", marker))

    query = urllib.parse.quote(f"subject:{marker}")
    with urllib.request.urlopen(f"{MAILPIT_API}/search?query={query}", timeout=5) as response:  # noqa: S310
        found = json.load(response)
    assert found["messages_count"] == 1
    message = found["messages"][0]
    assert message["To"][0]["Address"] == "dana@example.com"
    assert marker in message["Subject"]
