from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.config import Settings


class FetchError(Exception):
    pass


@dataclass(slots=True)
class FetchResult:
    url: str
    content: bytes
    content_type: str


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_EXPLICITLY_BLOCKED = {
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("169.254.169.254"),
}


def normalize_web_url(value: str) -> str:
    value = value.strip().rstrip(".,;:!?)]}'\"")
    if not value:
        raise FetchError("URL is empty")
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise FetchError("URL contains an invalid port") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise FetchError("only HTTP and HTTPS URLs are allowed")
    if not parsed.hostname:
        raise FetchError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise FetchError("URLs containing credentials are not allowed")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    netloc = host
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]"
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def is_forbidden_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return True
    return not ip.is_global or ip in _EXPLICITLY_BLOCKED


async def validate_public_url(url: str) -> str:
    normalized = normalize_web_url(url)
    parsed = urlsplit(normalized)
    host = parsed.hostname
    if host is None:
        raise FetchError("URL must include a hostname")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if is_forbidden_address(str(literal)):
            raise FetchError("URL resolves to a non-public address")
        return normalized

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        results = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise FetchError(f"could not resolve hostname {host}") from exc
    addresses = {item[4][0] for item in results}
    if not addresses or any(is_forbidden_address(address) for address in addresses):
        raise FetchError("URL resolves to a non-public address")
    return normalized


def _validate_peer(response: httpx.Response) -> None:
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        return
    peer = stream.get_extra_info("server_addr")
    if isinstance(peer, tuple) and peer and is_forbidden_address(str(peer[0])):
        raise FetchError("connection reached a non-public address")


class SafeFetcher:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    async def fetch(
        self,
        url: str,
        *,
        max_bytes: int,
        allowed_content_types: set[str],
    ) -> FetchResult:
        current = await validate_public_url(url)
        for redirect_count in range(self.settings.max_redirects + 1):
            try:
                async with self.client.stream(
                    "GET",
                    current,
                    follow_redirects=False,
                    headers={
                        "User-Agent": self.settings.user_agent,
                        "Accept": ", ".join(sorted(allowed_content_types)),
                    },
                ) as response:
                    _validate_peer(response)
                    if response.status_code in _REDIRECT_STATUSES:
                        if redirect_count >= self.settings.max_redirects:
                            raise FetchError("too many redirects")
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("redirect response has no location")
                        current = await validate_public_url(urljoin(current, location))
                        continue
                    if response.status_code in {401, 403}:
                        raise FetchError(f"remote server denied access ({response.status_code})")
                    if response.status_code >= 400:
                        raise FetchError(f"remote server returned HTTP {response.status_code}")

                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type not in allowed_content_types:
                        label = content_type or "unknown"
                        raise FetchError(f"unsupported content type: {label}")

                    declared_length = response.headers.get("content-length")
                    if declared_length:
                        try:
                            if int(declared_length) > max_bytes:
                                raise FetchError("remote content exceeds the size limit")
                        except ValueError:
                            pass

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise FetchError("remote content exceeds the size limit")
                    return FetchResult(current, bytes(body), content_type)
            except httpx.TimeoutException as exc:
                raise FetchError("remote request timed out") from exc
            except httpx.HTTPError as exc:
                raise FetchError(f"remote request failed: {exc}") from exc
        raise FetchError("too many redirects")


def make_http_client(settings: Settings) -> httpx.AsyncClient:
    timeout = httpx.Timeout(settings.fetch_timeout_seconds)
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    return httpx.AsyncClient(timeout=timeout, limits=limits, trust_env=False)
