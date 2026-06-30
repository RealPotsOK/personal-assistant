from __future__ import annotations

import contextlib
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import AuthContext, authenticate_bearer, bearer_token
from app.clients import QwenClient, ServiceHealth
from app.config import Settings, load_settings
from app.database import Database
from app.protocol import ProtocolError
from app.screen import ScreenError
from app.session import AssistantSession, SessionRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("personal_assistant")


class PairRequest(BaseModel):
    device_name: str | None = Field(default=None, max_length=120)


def _auth_from_header(
    authorization: str | None,
    settings: Settings,
    database: Database,
) -> AuthContext | None:
    token = bearer_token(authorization)
    return authenticate_bearer(token, settings, database) if token else None


async def require_http_auth(request: Request) -> AuthContext:
    auth = _auth_from_header(
        request.headers.get("authorization"),
        request.app.state.settings,
        request.app.state.database,
    )
    if auth is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Unauthorized"},
        )
    return auth


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()
    database = Database(
        config.database_path,
        max_turns=config.max_turns,
        max_memories=config.max_memories,
    )
    qwen = QwenClient(config)
    health = ServiceHealth(config, qwen)
    registry = SessionRegistry()
    pair_attempts: dict[str, deque[float]] = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await qwen.close()
        await health.close()
        database.close()

    app = FastAPI(title="Personal Assistant Session Controller", version="1.0.0", lifespan=lifespan)
    app.state.settings = config
    app.state.database = database
    app.state.registry = registry

    def _rate_limited(host: str) -> bool:
        now = time.monotonic()
        attempts = pair_attempts[host]
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= config.pairing_rate_limit_per_minute:
            return True
        attempts.append(now)
        return False

    @app.get("/live")
    async def live() -> dict:
        return {"status": "live"}

    @app.get("/health")
    async def health_check() -> JSONResponse:
        services = await health.all()
        core_ready = bool(services["qwen"].get("status") == "ready") and bool(
            services["whisper"].get("loaded")
        )
        return JSONResponse(
            {
                "status": "ready" if core_ready else "degraded",
                "active_session": registry.active,
                "paired_devices": database.device_count(),
                "pairing_enabled": config.pairing_enabled,
                "services": services,
            },
            status_code=200 if core_ready else 503,
        )

    @app.post("/pair", status_code=201)
    async def pair_device(request: Request, body: PairRequest) -> JSONResponse:
        if not config.pairing_enabled:
            raise HTTPException(
                status_code=403,
                detail={"code": "pairing_disabled", "message": "Pairing is disabled"},
            )
        client_host = request.client.host if request.client else "unknown"
        if _rate_limited(client_host):
            raise HTTPException(
                status_code=429,
                detail={"code": "pairing_rate_limited", "message": "Try again later"},
            )
        device = database.create_device(name=body.device_name)
        return JSONResponse(
            {
                "protocol": 1,
                "device_id": device["device_id"],
                "profile_id": device["profile_id"],
                "device_name": device["device_name"],
                "device_token": device["device_token"],
                "session_url": "/session",
            },
            status_code=201,
        )

    @app.post("/device/revoke-self")
    async def revoke_self(auth: Annotated[AuthContext, Depends(require_http_auth)]) -> dict:
        if auth.is_admin:
            raise HTTPException(
                status_code=400,
                detail={"code": "admin_token_not_revocable", "message": "Use a device token"},
            )
        revoked = database.revoke_device_token(auth.token)
        return {"revoked": revoked}

    @app.post("/setup/voice")
    async def setup_voice(
        reference_audio: Annotated[UploadFile, File()],
        auth: Annotated[AuthContext, Depends(require_http_auth)],
        name: Annotated[str | None, Form()] = None,
    ) -> JSONResponse:
        content_type = (reference_audio.content_type or "").lower()
        if content_type not in {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3"}:
            raise HTTPException(
                status_code=400,
                detail={"code": "unsupported_audio_type", "message": "Upload a WAV or MP3 reference"},
            )
        data = await reference_audio.read(config.max_voice_reference_bytes + 1)
        if len(data) > config.max_voice_reference_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "voice_reference_too_large",
                    "message": "Voice reference exceeds the configured limit",
                },
            )
        files = {
            "reference_audio": (
                reference_audio.filename or "reference.wav",
                data,
                reference_audio.content_type or "audio/wav",
            )
        }
        form = {"name": name or (auth.device_name if not auth.is_admin else "Windows voice")}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(config.upstream_timeout, read=None)) as client:
                response = await client.post(
                    f"{config.xtts_http_url}/voices/cache",
                    headers={"Authorization": f"Bearer {config.ai_api_key}"},
                    files=files,
                    data=form,
                )
        except Exception as error:
            return JSONResponse(
                {
                    "status": "unavailable",
                    "code": "xtts_unavailable",
                    "message": f"XTTS is unavailable; keep the reference for retry ({type(error).__name__})",
                },
                status_code=503,
            )
        if response.status_code >= 400:
            return JSONResponse(
                {
                    "status": "unavailable",
                    "code": "xtts_voice_setup_failed",
                    "message": response.text[:500],
                },
                status_code=response.status_code,
            )
        payload = response.json()
        return JSONResponse({"status": "ready", **payload}, status_code=201)

    @app.websocket("/session")
    async def session_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        auth = _auth_from_header(websocket.headers.get("authorization"), config, database)
        if auth is None:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        if not await registry.acquire():
            await websocket.close(code=4429, reason="Another PC session is active")
            return
        try:
            start = await websocket.receive_json()
            controller = AssistantSession(websocket, config, database, qwen, health, auth.profile_id)
            await controller.run(start)
        except WebSocketDisconnect:
            pass
        except (ProtocolError, ScreenError) as error:
            with contextlib.suppress(RuntimeError):
                await websocket.send_json(
                    {"type": "error", "code": "protocol_error", "message": str(error)}
                )
                await websocket.close(code=4400)
        except Exception as error:
            logger.exception("Session failed")
            with contextlib.suppress(RuntimeError):
                await websocket.send_json(
                    {"type": "error", "code": "session_failed", "message": str(error)[:300]}
                )
                await websocket.close(code=1011)
        finally:
            await registry.release()

    return app


app = create_app()
