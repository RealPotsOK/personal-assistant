from __future__ import annotations

import hmac
from dataclasses import dataclass

from app.config import Settings
from app.database import Database


@dataclass(frozen=True, slots=True)
class AuthContext:
    token: str
    kind: str
    profile_id: str | None = None
    device_id: str | None = None
    device_name: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"


def bearer_token(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def authenticate_bearer(token: str, settings: Settings, database: Database) -> AuthContext | None:
    if token and hmac.compare_digest(token, settings.client_token):
        return AuthContext(token=token, kind="admin")
    device = database.authenticate_device(token)
    if device:
        return AuthContext(
            token=token,
            kind="device",
            profile_id=device["profile_id"],
            device_id=device["device_id"],
            device_name=device.get("device_name"),
        )
    return None
