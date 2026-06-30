from __future__ import annotations

import asyncio
import gc
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.config import Settings
from app.core.audio import pcm16_to_float32
from app.errors import APIError, CapacityError, QueueFullError

logger = logging.getLogger("whisper_api.engine")
_END = object()


def serialize_segment(segment, *, offset: float = 0.0, include_words: bool = False) -> dict:
    result = {
        "id": segment.id,
        "seek": segment.seek,
        "start": round(float(segment.start) + offset, 3),
        "end": round(float(segment.end) + offset, 3),
        "text": segment.text.strip(),
        "tokens": list(segment.tokens),
        "temperature": segment.temperature,
        "avg_logprob": segment.avg_logprob,
        "compression_ratio": segment.compression_ratio,
        "no_speech_prob": segment.no_speech_prob,
    }
    if include_words:
        result["words"] = [
            {
                "word": word.word,
                "start": round(float(word.start) + offset, 3),
                "end": round(float(word.end) + offset, 3),
                "probability": word.probability,
            }
            for word in (segment.words or [])
        ]
    return result


class InferenceEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = None
        self.load_error: str | None = None
        self._load_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._waiters = 0

    @staticmethod
    def _is_capacity_error(error: BaseException) -> bool:
        text = str(error).lower()
        return any(term in text for term in ("out of memory", "cublas", "cudnn", "cuda error"))

    def _load_sync(self) -> None:
        from faster_whisper import WhisperModel

        model_path = Path(self.settings.model_path)
        required = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
        missing = [name for name in required if not (model_path / name).is_file()]
        if missing:
            raise RuntimeError(f"Whisper model files are missing: {', '.join(missing)}")
        self.model = WhisperModel(
            str(model_path),
            device=self.settings.device,
            compute_type=self.settings.compute_type,
            local_files_only=True,
            num_workers=1,
        )

    async def ensure_loaded(self) -> None:
        if self.model is not None:
            return
        async with self._load_lock:
            if self.model is not None:
                return
            self.load_error = None
            try:
                await asyncio.to_thread(self._load_sync)
                logger.info("Loaded %s from %s", self.settings.model_id, self.settings.model_path)
            except Exception as error:
                self.model = None
                self.load_error = str(error)
                gc.collect()
                logger.exception("Whisper model load failed")
                if self._is_capacity_error(error):
                    raise CapacityError() from error
                raise APIError(f"Whisper model is unavailable: {error}", 503, "model_unavailable") from error

    async def try_load(self) -> None:
        try:
            await self.ensure_loaded()
        except APIError:
            pass

    @asynccontextmanager
    async def slot(self):
        if self._inference_lock.locked() and self._waiters >= self.settings.max_queue:
            raise QueueFullError()
        self._waiters += 1
        try:
            await self._inference_lock.acquire()
        finally:
            self._waiters -= 1
        try:
            await self.ensure_loaded()
            yield
        except RuntimeError as error:
            if self._is_capacity_error(error):
                self.load_error = str(error)
                raise CapacityError() from error
            raise
        finally:
            self._inference_lock.release()

    def validate_request(self, *, language: str | None, task: str) -> str | None:
        if self.settings.model_variant == "small.en":
            if task == "translate":
                raise APIError(
                    "Translation requires the multilingual small model",
                    400,
                    "unsupported_model_capability",
                )
            if language not in {None, "en", "english"}:
                raise APIError("small.en only supports English", 400, "unsupported_language")
            return "en"
        return language

    @staticmethod
    def _info(info) -> dict:
        return {
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
            "duration_after_vad": getattr(info, "duration_after_vad", info.duration),
        }

    def _begin(self, audio, options: dict):
        return self.model.transcribe(audio, **options)

    @staticmethod
    def _next(iterator):
        try:
            return next(iterator)
        except StopIteration:
            return _END

    async def transcribe(self, audio, options: dict, *, offset: float = 0.0) -> dict:
        async with self.slot():
            segments, info = await asyncio.to_thread(self._begin, audio, options)

            def consume():
                return [
                    serialize_segment(
                        segment,
                        offset=offset,
                        include_words=bool(options.get("word_timestamps")),
                    )
                    for segment in segments
                ]

            items = await asyncio.to_thread(consume)
        return {
            "text": " ".join(item["text"] for item in items).strip(),
            **self._info(info),
            "segments": items,
        }

    async def transcribe_pcm(self, pcm: bytes, options: dict, *, offset: float = 0.0) -> dict:
        return await self.transcribe(pcm16_to_float32(pcm), options, offset=offset)

    async def stream(self, audio, options: dict) -> AsyncIterator[dict]:
        async with self.slot():
            segments, info = await asyncio.to_thread(self._begin, audio, options)
            text: list[str] = []
            while True:
                segment = await asyncio.to_thread(self._next, segments)
                if segment is _END:
                    break
                item = serialize_segment(segment, include_words=bool(options.get("word_timestamps")))
                text.append(item["text"])
                yield {"type": "segment", "data": item}
            yield {
                "type": "completed",
                "data": {"text": " ".join(text).strip(), **self._info(info)},
            }

    def status(self) -> dict:
        gpu = {}
        try:
            import pynvml

            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            gpu = {
                "gpu": name.decode() if isinstance(name, bytes) else name,
                "free_vram_bytes": memory.free,
                "total_vram_bytes": memory.total,
            }
        except Exception:
            pass
        return {
            "status": "ready" if self.model is not None else "degraded",
            "model": self.settings.model_id,
            "variant": self.settings.model_variant,
            "device": self.settings.device,
            "compute_type": self.settings.compute_type,
            "loaded": self.model is not None,
            "queue_depth": self._waiters,
            "load_error": self.load_error,
            **gpu,
        }
