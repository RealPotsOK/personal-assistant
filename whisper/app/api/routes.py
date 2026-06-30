from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from app.auth import auth_dependency, check_bearer
from app.config import Settings
from app.core.audio import store_upload
from app.core.engine import InferenceEngine
from app.core.live import LiveAudioBuffer, remove_word_overlap
from app.errors import APIError

logger = logging.getLogger("whisper_api.routes")


def create_router(settings: Settings, engine: InferenceEngine) -> APIRouter:
    router = APIRouter()
    authenticated = auth_dependency(settings)

    def validate_model(model: str | None) -> None:
        if model and model != settings.model_id:
            raise APIError(f"Unsupported model '{model}'", 400, "model_not_found")

    def options_for(
        *,
        language: str | None,
        prompt: str | None,
        temperature: float,
        word_timestamps: bool,
        task: str,
        partial: bool = False,
    ) -> dict:
        language = engine.validate_request(language=language, task=task)
        if not 0 <= temperature <= 1:
            raise APIError("temperature must be between 0 and 1", 400, "invalid_temperature")
        return {
            "language": language,
            "task": task,
            "initial_prompt": prompt or None,
            "temperature": temperature,
            "word_timestamps": word_timestamps,
            "beam_size": 1 if partial else 5,
            "condition_on_previous_text": False,
            "vad_filter": False,
        }

    def format_result(result: dict, response_format: str) -> Response:
        if response_format == "text":
            return PlainTextResponse(result["text"])
        if response_format == "json":
            return JSONResponse({"text": result["text"]})
        if response_format == "verbose_json":
            return JSONResponse(result)
        raise APIError(
            "response_format must be json, text, or verbose_json",
            400,
            "unsupported_response_format",
        )

    @router.get("/live")
    async def live() -> dict:
        return {"status": "live"}

    @router.get("/health")
    async def health() -> Response:
        status = engine.status()
        return Response(
            json.dumps(status),
            status_code=200 if status["loaded"] else 503,
            media_type="application/json",
        )

    @router.get("/v1/models", dependencies=[Depends(authenticated)])
    async def models() -> dict:
        return {
            "object": "list",
            "data": [{"id": settings.model_id, "object": "model", "owned_by": "local"}],
        }

    async def transcribe_upload(
        *,
        file: UploadFile,
        model: str | None,
        language: str | None,
        prompt: str | None,
        response_format: str,
        temperature: float,
        word_timestamps: bool,
        task: str,
    ) -> Response:
        validate_model(model)
        options = options_for(
            language=language,
            prompt=prompt,
            temperature=temperature,
            word_timestamps=word_timestamps,
            task=task,
        )
        audio = await store_upload(file, settings)
        try:
            result = await engine.transcribe(str(audio.path), options)
            return format_result(result, response_format)
        finally:
            audio.close()

    @router.post("/v1/audio/transcriptions", dependencies=[Depends(authenticated)])
    async def transcriptions(
        file: Annotated[UploadFile, File()],
        model: Annotated[str | None, Form()] = None,
        language: Annotated[str | None, Form()] = None,
        prompt: Annotated[str | None, Form()] = None,
        response_format: Annotated[str, Form()] = "json",
        temperature: Annotated[float, Form()] = 0,
        word_timestamps: Annotated[bool, Form()] = False,
    ) -> Response:
        return await transcribe_upload(
            file=file,
            model=model,
            language=language,
            prompt=prompt,
            response_format=response_format,
            temperature=temperature,
            word_timestamps=word_timestamps,
            task="transcribe",
        )

    @router.post("/v1/audio/translations", dependencies=[Depends(authenticated)])
    async def translations(
        file: Annotated[UploadFile, File()],
        model: Annotated[str | None, Form()] = None,
        prompt: Annotated[str | None, Form()] = None,
        response_format: Annotated[str, Form()] = "json",
        temperature: Annotated[float, Form()] = 0,
        word_timestamps: Annotated[bool, Form()] = False,
    ) -> Response:
        return await transcribe_upload(
            file=file,
            model=model,
            language=None,
            prompt=prompt,
            response_format=response_format,
            temperature=temperature,
            word_timestamps=word_timestamps,
            task="translate",
        )

    @router.post("/transcribe/stream", dependencies=[Depends(authenticated)])
    async def stream_transcription(
        file: Annotated[UploadFile, File()],
        model: Annotated[str | None, Form()] = None,
        language: Annotated[str | None, Form()] = None,
        prompt: Annotated[str | None, Form()] = None,
        temperature: Annotated[float, Form()] = 0,
        word_timestamps: Annotated[bool, Form()] = False,
    ) -> StreamingResponse:
        validate_model(model)
        options = options_for(
            language=language,
            prompt=prompt,
            temperature=temperature,
            word_timestamps=word_timestamps,
            task="transcribe",
        )
        audio = await store_upload(file, settings)

        async def events():
            try:
                async for event in engine.stream(str(audio.path), options):
                    name = "transcript.segment" if event["type"] == "segment" else "transcript.completed"
                    yield f"event: {name}\ndata: {json.dumps(event['data'])}\n\n"
            except APIError as error:
                yield f"event: error\ndata: {json.dumps({'code': error.code, 'message': error.message})}\n\n"
            finally:
                audio.close()

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @router.websocket("/ws/transcribe")
    async def live_transcription(websocket: WebSocket) -> None:
        try:
            check_bearer(websocket.headers.get("authorization"), settings)
        except APIError:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await websocket.accept()
        worker: asyncio.Task | None = None
        queue: asyncio.Queue = asyncio.Queue(maxsize=16)
        cancelled = False
        try:
            start = await websocket.receive_json()
            if start.get("type") != "start":
                raise APIError("First event must be start", 400, "invalid_start")
            if start.get("sample_rate", 16_000) != 16_000:
                raise APIError("Live audio must be 16 kHz", 400, "invalid_sample_rate")
            if start.get("channels", 1) != 1 or start.get("sample_format", "s16le") != "s16le":
                raise APIError("Live audio must be mono PCM16 little-endian", 400, "invalid_audio_format")
            task = str(start.get("task", "transcribe"))
            if task not in {"transcribe", "translate"}:
                raise APIError("task must be transcribe or translate", 400, "invalid_task")
            language = start.get("language")
            prompt = start.get("prompt")
            word_timestamps = bool(start.get("word_timestamps", False))
            partial_options = options_for(
                language=language,
                prompt=prompt,
                temperature=0,
                word_timestamps=False,
                task=task,
                partial=True,
            )
            final_options = options_for(
                language=language,
                prompt=prompt,
                temperature=0,
                word_timestamps=word_timestamps,
                task=task,
            )
            live_buffer = LiveAudioBuffer(
                partial_interval_ms=settings.partial_interval_ms,
                final_silence_ms=settings.final_silence_ms,
                max_utterance_ms=settings.max_utterance_ms,
                overlap_ms=settings.overlap_ms,
            )
            await websocket.send_json(
                {
                    "type": "ready",
                    "sample_rate": 16_000,
                    "channels": 1,
                    "sample_format": "s16le",
                    "model": settings.model_id,
                }
            )

            async def produce() -> None:
                previous_final = ""
                dedupe_next_final = False
                while True:
                    job = await queue.get()
                    if job is None:
                        await websocket.send_json({"type": "cancelled" if cancelled else "done"})
                        return
                    options = partial_options if job.kind == "partial" else final_options
                    result = await engine.transcribe_pcm(job.pcm, options, offset=job.offset_seconds)
                    if cancelled:
                        continue
                    text = result["text"]
                    if job.kind == "final" and dedupe_next_final:
                        text = remove_word_overlap(previous_final, text)
                    event = {
                        "type": job.kind,
                        "utterance_id": job.utterance_id,
                        "revision": job.revision,
                        "text": text,
                        "language": result["language"],
                        "language_probability": result["language_probability"],
                    }
                    if job.kind == "final":
                        event["segments"] = result["segments"]
                        event["forced"] = job.forced
                        previous_final = f"{previous_final} {text}".strip()
                        dedupe_next_final = job.forced
                    await websocket.send_json(event)

            worker = asyncio.create_task(produce())
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                if message.get("bytes") is not None:
                    for job in live_buffer.feed(message["bytes"]):
                        if job.kind == "partial" and queue.full():
                            continue
                        await queue.put(job)
                    continue
                if message.get("text") is None:
                    continue
                try:
                    control = json.loads(message["text"])
                except json.JSONDecodeError as error:
                    raise APIError("Control events must be valid JSON", 400, "invalid_event") from error
                kind = control.get("type")
                if kind == "commit":
                    if job := live_buffer.commit():
                        await queue.put(job)
                elif kind == "finish":
                    if job := live_buffer.commit():
                        await queue.put(job)
                    await queue.put(None)
                    await worker
                    return
                elif kind == "cancel":
                    cancelled = True
                    while not queue.empty():
                        queue.get_nowait()
                    await queue.put(None)
                    await worker
                    return
                else:
                    raise APIError(f"Unsupported event type '{kind}'", 400, "invalid_event")
        except WebSocketDisconnect:
            if worker and not worker.done():
                worker.cancel()
        except APIError as error:
            if worker and not worker.done():
                worker.cancel()
            await websocket.send_json({"type": "error", "code": error.code, "message": error.message})
            await websocket.close(code=4400)
        except Exception as error:
            if worker and not worker.done():
                worker.cancel()
            logger.exception("Live transcription failed")
            try:
                await websocket.send_json({"type": "error", "code": "internal_error", "message": str(error)})
                await websocket.close(code=1011)
            except RuntimeError:
                pass

    return router
