import httpx
import pytest

from app.config import settings
from app.core.safe_http import (
    FetchError,
    SafeFetcher,
    is_forbidden_address,
    normalize_web_url,
    validate_public_url,
)


def test_normalizes_bare_domain() -> None:
    assert normalize_web_url("coffeeandcafe.com/menu") == "https://coffeeandcafe.com/menu"


def test_rejects_credentials_and_non_http_protocols() -> None:
    with pytest.raises(FetchError):
        normalize_web_url("https://user:password@example.com/")
    with pytest.raises(FetchError):
        normalize_web_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_rejects_loopback_literal() -> None:
    with pytest.raises(FetchError, match="non-public"):
        await validate_public_url("http://127.0.0.1/private")


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "192.168.1.1"],
)
def test_forbidden_networks(address: str) -> None:
    assert is_forbidden_address(address)


def test_public_address_is_allowed() -> None:
    assert not is_forbidden_address("1.1.1.1")


@pytest.mark.asyncio
async def test_fetcher_follows_validated_redirect(monkeypatch) -> None:
    validated: list[str] = []

    async def fake_validate(url: str) -> str:
        normalized = normalize_web_url(url)
        validated.append(normalized)
        return normalized

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok")

    monkeypatch.setattr("app.core.safe_http.validate_public_url", fake_validate)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SafeFetcher(settings, client).fetch(
            "https://example.com/start",
            max_bytes=100,
            allowed_content_types={"text/html"},
        )
    assert result.url == "https://example.com/final"
    assert validated == ["https://example.com/start", "https://example.com/final"]
