from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import create_router
from app.config import Settings, settings
from app.core.inference import InferenceEngine
from app.errors import APIError, error_body


logger = logging.getLogger("qwen3_vl_api")


def create_app(
    app_settings: Settings = settings,
    engine: InferenceEngine | None = None,
    *,
    load_model: bool = True,
) -> FastAPI:
    inference_engine = engine or InferenceEngine(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if load_model:
            logger.info("Loading model from %s", app_settings.model_path)
            await inference_engine.load()
            logger.info("Model loaded")
        yield

    application = FastAPI(
        title="Qwen3-VL API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.engine = inference_engine
    application.state.settings = app_settings
    application.include_router(create_router(app_settings, inference_engine))

    @application.exception_handler(APIError)
    async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            error_body(
                exc.message,
                error_type=exc.error_type,
                param=exc.param,
                code=exc.code,
            ),
            status_code=exc.status_code,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = first.get("loc", ())
        param = ".".join(str(item) for item in location if item != "body") or None
        message = first.get("msg", "request validation failed")
        return JSONResponse(
            error_body(message, param=param, code="validation_error"),
            status_code=400,
        )

    return application


app = create_app()
