from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import av
from fastapi import UploadFile

from app.config import Settings
from app.errors import APIError


@dataclass(slots=True)
class StoredAudio:
    directory: tempfile.TemporaryDirectory
    path: Path
    seconds: float

    def close(self) -> None:
        self.directory.cleanup()


def _probe(path: Path, max_seconds: int) -> float:
    try:
        with av.open(str(path)) as container:
            streams = list(container.streams.audio)
            if not streams:
                raise APIError("The upload has no audio stream", 400, "invalid_audio")
            stream = streams[0]
            duration = 0.0
            for frame in container.decode(stream):
                rate = frame.sample_rate or stream.rate or 16_000
                duration += frame.samples / rate
                if duration > max_seconds:
                    break
    except APIError:
        raise
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise APIError("The audio could not be decoded", 400, "invalid_audio") from exc
    if duration <= 0:
        raise APIError("The audio is empty", 400, "empty_audio")
    if duration > max_seconds:
        raise APIError("The audio exceeds the configured duration limit", 413, "audio_too_long")
    return duration


async def store_upload(upload: UploadFile, settings: Settings) -> StoredAudio:
    allowed = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "application/octet-stream"}
    if upload.content_type not in allowed:
        raise APIError("Only WAV and MP3 uploads are supported", 415, "unsupported_audio_type")
    directory = tempfile.TemporaryDirectory(prefix="whisper-upload-")
    filename = (upload.filename or "").lower()
    is_mp3 = upload.content_type in {"audio/mpeg", "audio/mp3"} or filename.endswith(".mp3")
    suffix = ".mp3" if is_mp3 else ".wav"
    path = Path(directory.name) / f"audio{suffix}"
    size = 0
    try:
        with path.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_audio_bytes:
                    raise APIError("The audio exceeds the configured size limit", 413, "audio_too_large")
                handle.write(chunk)
        if not size:
            raise APIError("The audio is empty", 400, "empty_audio")
        seconds = _probe(path, settings.max_audio_seconds)
        return StoredAudio(directory, path, seconds)
    except Exception:
        directory.cleanup()
        raise


def pcm16_to_float32(data: bytes):
    import numpy as np

    if len(data) % 2:
        raise APIError("PCM16 audio must contain complete 16-bit samples", 400, "invalid_pcm")
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
