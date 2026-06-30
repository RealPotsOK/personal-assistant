from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import create_router
from app.config import Settings, load_settings
from app.core.engine import InferenceEngine
from app.errors import APIError, error_body
from app.voice_store import VoiceStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(
    settings: Settings | None = None,
    engine: InferenceEngine | None = None,
    store: VoiceStore | None = None,
    *,
    load_model: bool = True,
) -> FastAPI:
    app_settings = settings or load_settings()
    inference = engine or InferenceEngine(app_settings)
    voices = store or VoiceStore(app_settings.voice_dir, app_settings.model_id)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if load_model:
            await inference.try_load()
        yield

    app = FastAPI(
        title="XTTS Voice API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.engine = inference
    app.state.voice_store = voices
    app.include_router(create_router(app_settings, inference, voices))

    @app.exception_handler(APIError)
    async def api_error(_: Request, error: APIError) -> JSONResponse:
        return JSONResponse(error_body(error.message, error.code), status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        first = error.errors()[0] if error.errors() else {}
        return JSONResponse(
            error_body(str(first.get("msg", "Request validation failed")), "validation_error"),
            status_code=400,
        )

    return app


app = create_app()
