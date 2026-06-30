from __future__ import annotations

import hmac

from fastapi import Header

from app.config import Settings
from app.errors import APIError


def auth_dependency(settings: Settings):
    async def authenticate(authorization: str | None = Header(default=None)) -> None:
        prefix = "Bearer "
        if not authorization or not authorization.startswith(prefix):
            raise APIError("A bearer API key is required", status_code=401, code="unauthorized")
        if not hmac.compare_digest(authorization[len(prefix) :], settings.api_key):
            raise APIError("The API key is invalid", status_code=401, code="unauthorized")

    return authenticate
