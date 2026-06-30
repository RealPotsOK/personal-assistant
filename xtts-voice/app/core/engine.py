from __future__ import annotations

import asyncio
import gc
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.config import Settings
from app.core.audio import floats_to_pcm
from app.core.text import split_text
from app.errors import APIError, CapacityError, QueueFullError

logger = logging.getLogger("xtts_voice.engine")
_END = object()


class InferenceEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = None
        self.config = None
        self.device = None
        self.load_error: str | None = None
        self._load_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._waiters = 0

    @staticmethod
    def _is_oom(error: BaseException) -> bool:
        text = str(error).lower()
        return "out of memory" in text or "cuda error" in text and "memory" in text

    def _clear_cuda(self) -> None:
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()

    def _load_sync(self) -> None:
        import torch
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import Xtts

        model_path = Path(self.settings.model_path)
        required = ["config.json", "model.pth", "vocab.json", "dvae.pth", "mel_stats.pth"]
        missing = [name for name in required if not (model_path / name).is_file()]
        if missing:
            raise RuntimeError(f"XTTS model files are missing: {', '.join(missing)}")
        if self.settings.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is required but unavailable")

        config = XttsConfig()
        config.load_json(str(model_path / "config.json"))
        model = Xtts.init_from_config(config)
        model.load_checkpoint(config, checkpoint_dir=str(model_path), eval=True, use_deepspeed=False)
        if self.settings.device == "cuda":
            model.cuda()
            self.device = torch.device("cuda")
        else:
            model.cpu()
            self.device = torch.device("cpu")
        model.eval()
        self.config = config
        self.model = model

    async def ensure_loaded(self) -> None:
        if self.model is not None:
            return
        async with self._load_lock:
            if self.model is not None:
                return
            self.load_error = None
            try:
                await asyncio.to_thread(self._load_sync)
                logger.info("XTTS model loaded from %s", self.settings.model_path)
            except Exception as error:
                self.model = None
                self.config = None
                self._clear_cuda()
                self.load_error = str(error)
                logger.exception("XTTS model load failed")
                if self._is_oom(error):
                    raise CapacityError() from error
                raise APIError(f"XTTS model is unavailable: {error}", 503, "model_unavailable") from error

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
            if self._is_oom(error):
                self.model = None
                self.config = None
                self.load_error = str(error)
                self._clear_cuda()
                raise CapacityError() from error
            raise
        finally:
            self._inference_lock.release()

    def _to_device(self, tensor):
        return tensor.to(self.device)

    async def condition(self, audio_path: Path):
        async with self.slot():
            return await asyncio.to_thread(
                self.model.get_conditioning_latents,
                audio_path=[str(audio_path)],
                max_ref_length=self.settings.max_reference_seconds,
                gpt_cond_len=min(12, self.settings.max_reference_seconds),
                gpt_cond_chunk_len=6,
                sound_norm_refs=True,
            )

    def _inference_sync(self, segment: str, language: str, conditioning, embedding):
        return self.model.inference(
            segment,
            language,
            self._to_device(conditioning),
            self._to_device(embedding),
        )["wav"]

    async def synthesize(self, text: str, language: str, conditioning, embedding) -> bytes:
        segments = split_text(text, self.settings.max_segment_chars)
        if not segments:
            raise APIError("text cannot be blank", 400, "invalid_text")
        output = bytearray()
        async with self.slot():
            for index, segment in enumerate(segments):
                samples = await asyncio.to_thread(
                    self._inference_sync, segment, language, conditioning, embedding
                )
                output.extend(floats_to_pcm(samples))
                if index + 1 < len(segments):
                    output.extend(b"\x00\x00" * int(self.settings.sample_rate * 0.08))
        return bytes(output)

    def _stream_sync(self, segment: str, language: str, conditioning, embedding):
        return self.model.inference_stream(
            segment,
            language,
            self._to_device(conditioning),
            self._to_device(embedding),
            stream_chunk_size=self.settings.stream_chunk_size,
        )

    @staticmethod
    def _next(iterator):
        try:
            return next(iterator)
        except StopIteration:
            return _END

    async def stream_segment(
        self, segment: str, language: str, conditioning, embedding
    ) -> AsyncIterator[bytes]:
        async with self.slot():
            iterator = self._stream_sync(segment, language, conditioning, embedding)
            try:
                while True:
                    try:
                        next_chunk = asyncio.create_task(asyncio.to_thread(self._next, iterator))
                        try:
                            chunk = await next_chunk
                        except asyncio.CancelledError:
                            await asyncio.shield(next_chunk)
                            raise
                    except RuntimeError as error:
                        if self._is_oom(error):
                            self.model = None
                            self.config = None
                            self.load_error = str(error)
                            self._clear_cuda()
                            raise CapacityError() from error
                        raise
                    if chunk is _END:
                        break
                    yield floats_to_pcm(chunk.detach().cpu().numpy())
            finally:
                close = getattr(iterator, "close", None)
                if close:
                    close()

    async def stream(self, text: str, language: str, conditioning, embedding) -> AsyncIterator[bytes]:
        segments = split_text(text, self.settings.max_segment_chars)
        for index, segment in enumerate(segments):
            async for chunk in self.stream_segment(segment, language, conditioning, embedding):
                yield chunk
            if index + 1 < len(segments):
                yield b"\x00\x00" * int(self.settings.sample_rate * 0.08)

    def status(self) -> dict:
        gpu: dict = {}
        try:
            import torch

            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                gpu = {
                    "name": torch.cuda.get_device_name(0),
                    "free_vram_bytes": free,
                    "total_vram_bytes": total,
                }
        except Exception:
            pass
        return {
            "status": "ready" if self.model is not None else "degraded",
            "model": self.settings.model_id,
            "device": self.settings.device,
            "loaded": self.model is not None,
            "queue_depth": self._waiters,
            "load_error": self.load_error,
            **gpu,
        }
