import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_cors_origins_accepts_comma_separated_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test,")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_jwt_expiry_defaults_to_eight_hours() -> None:
    assert Settings().jwt_expire_minutes == 480


@pytest.mark.parametrize("url", ["https://ntfy.sh", "https://ntfy.sh/topic", "http://x.ntfy.sh:80"])
def test_public_ntfy_server_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(ntfy_base_url=url)


def test_self_hosted_ntfy_is_allowed() -> None:
    assert Settings(ntfy_publish_url="http://ntfy:80").ntfy_publish_url == "http://ntfy:80"


def test_cors_middleware_enabled_only_when_origins_configured(settings: Settings) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    preflight = {"Origin": "http://allowed.test", "Access-Control-Request-Method": "GET"}
    with TestClient(
        create_app(settings.model_copy(update={"cors_origins": ["http://allowed.test"]}))
    ) as client:
        response = client.options("/health", headers=preflight)
        assert response.headers["access-control-allow-origin"] == "http://allowed.test"
    with TestClient(create_app(settings.model_copy(update={"cors_origins": []}))) as client:
        response = client.options("/health", headers=preflight)
        assert "access-control-allow-origin" not in response.headers
