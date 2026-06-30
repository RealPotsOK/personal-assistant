from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse

from app.auth import auth_dependency
from app.config import Settings
from app.core.inference import InferenceEngine
from app.core.messages import accepted_model_ids, prepare_messages
from app.errors import APIError, error_body
from app.schemas.chat import ChatCompletionRequest


logger = logging.getLogger("qwen3_vl_api.routes")


def _completion_id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex


def _sse(data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
    return f"data: {payload}\n\n"


def create_router(settings: Settings, engine: InferenceEngine) -> APIRouter:
    router = APIRouter()
    authenticated = auth_dependency(settings)

    @router.get("/health")
    async def health() -> JSONResponse:
        body = {
            "status": "ready" if engine.ready else "not_ready",
            "model": settings.model_id,
            "device": "cuda",
            "quantization": settings.quantization,
            "queue_depth": getattr(engine, "queue_depth", 0),
        }
        if engine.load_error:
            body["error"] = engine.load_error
        return JSONResponse(body, status_code=200 if engine.ready else 503)

    @router.get("/v1/models", dependencies=[Depends(authenticated)])
    async def models() -> dict:
        return {
            "object": "list",
            "data": [
                {
                    "id": settings.model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "local",
                }
            ],
        }

    @router.post("/v1/chat/completions", dependencies=[Depends(authenticated)])
    async def chat_completions(
        request: ChatCompletionRequest,
        priority: Annotated[
            Literal["realtime", "normal", "background"], Header(alias="X-AI-Priority")
        ] = "normal",
    ):
        if request.model not in accepted_model_ids(settings):
            raise APIError(
                f"model '{request.model}' is not available",
                status_code=404,
                param="model",
                code="model_not_found",
            )
        if not engine.ready:
            raise APIError(
                "model is not ready",
                status_code=503,
                error_type="server_error",
                code="model_not_ready",
            )
        max_tokens = request.requested_max_tokens(settings.default_max_tokens)
        if max_tokens > settings.max_tokens:
            raise APIError(
                f"max_tokens cannot exceed {settings.max_tokens}",
                param="max_tokens",
                code="max_tokens_exceeded",
            )

        messages, web_sources = await prepare_messages(request, settings)
        completion_id = _completion_id()
        created = int(time.time())

        if request.stream:
            return StreamingResponse(
                _stream_completion(
                    engine,
                    messages,
                    completion_id=completion_id,
                    created=created,
                    model=settings.model_id,
                    max_tokens=max_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    priority=priority,
                    web_sources=web_sources,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        try:
            result = await engine.generate(
                messages,
                max_tokens=max_tokens,
                temperature=request.temperature,
                top_p=request.top_p,
                priority=priority,
            )
        except Exception as exc:
            logger.exception("Model generation failed")
            raise APIError(
                "model generation failed",
                status_code=500,
                error_type="server_error",
                code="generation_failed",
            ) from exc
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": settings.model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result.text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.prompt_tokens + result.completion_tokens,
            },
            "web_sources": web_sources,
        }

    return router


async def _stream_completion(
    engine: InferenceEngine,
    messages: list[dict],
    *,
    completion_id: str,
    created: int,
    model: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    priority: str,
    web_sources: list[dict[str, str]],
) -> AsyncIterator[str]:
    base = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
    }
    first = {
        **base,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        "web_sources": web_sources,
    }
    yield _sse(first)
    try:
        async for text in engine.stream(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            priority=priority,
        ):
            yield _sse(
                {
                    **base,
                    "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                }
            )
        yield _sse(
            {
                **base,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        )
    except Exception:
        logger.exception("Model generation failed while streaming")
        yield _sse(
            error_body(
                "model generation failed while streaming",
                error_type="server_error",
                code="generation_failed",
            )
        )
    yield _sse("[DONE]")
