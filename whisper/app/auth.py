from __future__ import annotations

import hmac

from fastapi import Header

from app.config import Settings
from app.errors import APIError


def check_bearer(authorization: str | None, settings: Settings) -> None:
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise APIError("A bearer API key is required", 401, "unauthorized")
    if not hmac.compare_digest(authorization[len(prefix) :], settings.api_key):
        raise APIError("The API key is invalid", 401, "unauthorized")


def auth_dependency(settings: Settings):
    async def authenticate(authorization: str | None = Header(default=None)) -> None:
        check_bearer(authorization, settings)

    return authenticate
