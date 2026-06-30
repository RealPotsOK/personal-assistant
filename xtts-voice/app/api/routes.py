from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse

from app.auth import auth_dependency, check_bearer
from app.config import Settings
from app.core.audio import normalize_reference, pcm_to_wav
from app.core.engine import InferenceEngine
from app.core.text import pop_committed, split_text
from app.errors import APIError
from app.schemas import OpenAISpeechRequest, SpeechRequest
from app.voice_store import VoiceStore

logger = logging.getLogger("xtts_voice.routes")


def create_router(settings: Settings, engine: InferenceEngine, store: VoiceStore) -> APIRouter:
    router = APIRouter()
    authenticated = auth_dependency(settings)

    def validate_text(text: str) -> str:
        text = text.strip()
        if not text:
            raise APIError("text cannot be blank", 400, "invalid_text")
        if len(text) > settings.max_text_chars:
            raise APIError(
                f"text exceeds the {settings.max_text_chars} character limit", 400, "text_too_long"
            )
        return text

    async def validate_language(language: str) -> str:
        await engine.ensure_loaded()
        languages = list(getattr(engine.config, "languages", []) or [])
        if languages and language not in languages:
            raise APIError(
                f"Unsupported language '{language}'. Supported values: {', '.join(languages)}",
                400,
                "unsupported_language",
            )
        return language

    def pcm_headers() -> dict[str, str]:
        return {
            "X-Audio-Sample-Rate": str(settings.sample_rate),
            "X-Audio-Channels": "1",
            "X-Audio-Sample-Format": "s16le",
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        }

    @router.get("/live")
    async def live() -> dict:
        return {"status": "live"}

    @router.get("/health")
    async def health() -> Response:
        status = engine.status()
        return Response(
            content=json.dumps(status),
            status_code=200 if status["loaded"] else 503,
            media_type="application/json",
        )

    @router.get("/v1/models", dependencies=[Depends(authenticated)])
    async def models() -> dict:
        return {
            "object": "list",
            "data": [{"id": settings.model_id, "object": "model", "owned_by": "local"}],
        }

    @router.post("/voices/preview", dependencies=[Depends(authenticated)])
    async def preview_voice(
        text: Annotated[str, Form()],
        reference_audio: Annotated[UploadFile, File()],
        language: Annotated[str, Form()] = "en",
    ) -> Response:
        text = validate_text(text)
        language = await validate_language(language)
        reference = await normalize_reference(reference_audio, settings)
        started = time.perf_counter()
        try:
            conditioning, embedding = await engine.condition(reference.path)
            pcm = await engine.synthesize(text, language, conditioning, embedding)
        finally:
            reference.close()
        logger.info("voice preview completed in %.3fs", time.perf_counter() - started)
        return Response(
            pcm_to_wav(pcm, settings.sample_rate),
            media_type="audio/wav",
            headers={"Content-Disposition": 'inline; filename="preview.wav"', "Cache-Control": "no-store"},
        )

    @router.post("/voices/cache", dependencies=[Depends(authenticated)], status_code=201)
    async def cache_voice(
        reference_audio: Annotated[UploadFile, File()],
        name: Annotated[str | None, Form()] = None,
    ) -> dict:
        reference = await normalize_reference(reference_audio, settings)
        try:
            conditioning, embedding = await engine.condition(reference.path)
            return store.save(
                conditioning,
                embedding,
                name=name,
                reference_seconds=reference.seconds,
            )
        finally:
            reference.close()

    @router.get("/voices", dependencies=[Depends(authenticated)])
    async def list_voices() -> dict:
        return {"data": store.list()}

    @router.delete("/voices/{voice_id}", dependencies=[Depends(authenticated)], status_code=204)
    async def delete_voice(voice_id: str) -> Response:
        store.delete(voice_id)
        return Response(status_code=204)

    @router.post("/tts", dependencies=[Depends(authenticated)])
    async def speech(body: SpeechRequest) -> Response:
        text = validate_text(body.text)
        language = await validate_language(body.language)
        conditioning, embedding = store.get(body.voice_id)
        pcm = await engine.synthesize(text, language, conditioning, embedding)
        return Response(
            pcm_to_wav(pcm, settings.sample_rate),
            media_type="audio/wav",
            headers={"Content-Disposition": 'inline; filename="speech.wav"', "Cache-Control": "no-store"},
        )

    @router.post("/tts/stream", dependencies=[Depends(authenticated)])
    async def stream_speech(body: SpeechRequest) -> StreamingResponse:
        text = validate_text(body.text)
        language = await validate_language(body.language)
        conditioning, embedding = store.get(body.voice_id)

        async def generate() -> AsyncIterator[bytes]:
            async for chunk in engine.stream(text, language, conditioning, embedding):
                yield chunk

        return StreamingResponse(
            generate(),
            media_type="audio/pcm;rate=24000;channels=1;format=s16le",
            headers=pcm_headers(),
        )

    @router.post("/v1/audio/speech", dependencies=[Depends(authenticated)])
    async def openai_speech(body: OpenAISpeechRequest) -> Response:
        if body.model != settings.model_id:
            raise APIError(f"Unsupported model '{body.model}'", 400, "model_not_found")
        if body.response_format != "wav":
            raise APIError("Only response_format=wav is supported", 400, "unsupported_value")
        if body.speed != 1.0:
            raise APIError("Only speed=1.0 is supported", 400, "unsupported_value")
        text = validate_text(body.input)
        language = await validate_language(body.language)
        conditioning, embedding = store.get(body.voice)
        pcm = await engine.synthesize(text, language, conditioning, embedding)
        return Response(pcm_to_wav(pcm, settings.sample_rate), media_type="audio/wav")

    @router.websocket("/ws/tts")
    async def websocket_speech(websocket: WebSocket) -> None:
        try:
            check_bearer(websocket.headers.get("authorization"), settings)
        except APIError:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await websocket.accept()
        send_lock = asyncio.Lock()
        segment_queue: asyncio.Queue[str | None] = asyncio.Queue()
        state = {"buffer": "", "total": 0, "cancelled": False}

        async def send_json(payload: dict) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        async def send_audio(payload: bytes) -> None:
            async with send_lock:
                await websocket.send_bytes(payload)

        try:
            start = await websocket.receive_json()
            if start.get("type") != "start" or not isinstance(start.get("voice_id"), str):
                await send_json(
                    {
                        "type": "error",
                        "code": "invalid_start",
                        "message": "First event must be start with voice_id",
                    }
                )
                await websocket.close(code=4400)
                return
            language = str(start.get("language", "en"))
            await validate_language(language)
            conditioning, embedding = store.get(start["voice_id"])
            await send_json(
                {
                    "type": "ready",
                    "sample_rate": settings.sample_rate,
                    "channels": 1,
                    "sample_format": "s16le",
                }
            )

            async def receive_text() -> None:
                while True:
                    event = await websocket.receive_json()
                    kind = event.get("type")
                    if kind == "text_delta":
                        delta = event.get("text")
                        if not isinstance(delta, str):
                            raise APIError("text_delta.text must be a string", 400, "invalid_event")
                        state["total"] += len(delta)
                        if state["total"] > settings.max_text_chars:
                            raise APIError("WebSocket text limit exceeded", 400, "text_too_long")
                        state["buffer"] += delta
                        committed, state["buffer"] = pop_committed(
                            state["buffer"], settings.max_segment_chars
                        )
                        for segment in committed:
                            await segment_queue.put(segment)
                    elif kind == "commit":
                        for segment in split_text(state["buffer"], settings.max_segment_chars):
                            await segment_queue.put(segment)
                        state["buffer"] = ""
                    elif kind == "finish":
                        for segment in split_text(state["buffer"], settings.max_segment_chars):
                            await segment_queue.put(segment)
                        state["buffer"] = ""
                        await segment_queue.put(None)
                        return
                    elif kind == "cancel":
                        state["cancelled"] = True
                        while not segment_queue.empty():
                            segment_queue.get_nowait()
                        await segment_queue.put(None)
                        return
                    else:
                        raise APIError(f"Unsupported event type '{kind}'", 400, "invalid_event")

            async def produce_audio() -> None:
                index = 0
                while True:
                    segment = await segment_queue.get()
                    if segment is None or state["cancelled"]:
                        break
                    index += 1
                    await send_json({"type": "segment_start", "index": index})
                    async for chunk in engine.stream_segment(segment, language, conditioning, embedding):
                        if state["cancelled"]:
                            break
                        await send_audio(chunk)
                    if not state["cancelled"]:
                        await send_json({"type": "segment_end", "index": index})
                await send_json({"type": "cancelled" if state["cancelled"] else "done"})

            receiver = asyncio.create_task(receive_text())
            producer = asyncio.create_task(produce_audio())
            pending: set[asyncio.Task] = set()
            try:
                done, pending = await asyncio.wait(
                    {receiver, producer}, return_when=asyncio.FIRST_EXCEPTION
                )
                for task in done:
                    error = task.exception()
                    if error:
                        raise error
                if pending:
                    await asyncio.gather(*pending)
            finally:
                for task in pending:
                    if not task.done():
                        task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
        except WebSocketDisconnect:
            return
        except APIError as error:
            try:
                await send_json({"type": "error", "code": error.code, "message": error.message})
                await websocket.close(code=4400)
            except RuntimeError:
                pass
        except Exception as error:
            logger.exception("WebSocket synthesis failed")
            try:
                await send_json({"type": "error", "code": "internal_error", "message": str(error)})
                await websocket.close(code=1011)
            except RuntimeError:
                pass

    return router
