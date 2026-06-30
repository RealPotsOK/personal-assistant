from __future__ import annotations

import io
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from fastapi import UploadFile

from app.config import Settings
from app.errors import APIError


@dataclass(slots=True)
class NormalizedReference:
    directory: tempfile.TemporaryDirectory
    path: Path
    seconds: float
    warnings: list[dict[str, object]]

    def close(self) -> None:
        self.directory.cleanup()


async def normalize_reference(upload: UploadFile, settings: Settings) -> NormalizedReference:
    allowed = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3"}
    if upload.content_type not in allowed:
        raise APIError("reference_audio must be a WAV or MP3 file", 415, "unsupported_audio_type")
    directory = tempfile.TemporaryDirectory(prefix="xtts-reference-")
    source = Path(directory.name) / "source"
    target = Path(directory.name) / "normalized.wav"
    total = 0
    try:
        with source.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_reference_bytes:
                    raise APIError(
                        "reference_audio exceeds the configured size limit", 413, "reference_too_large"
                    )
                handle.write(chunk)
        if not total:
            raise APIError("reference_audio is empty", 400, "empty_reference")
        process = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                str(settings.sample_rate),
                "-c:a",
                "pcm_s16le",
                "-y",
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if process.returncode != 0:
            raise APIError("reference_audio could not be decoded", 400, "invalid_reference_audio")
        with wave.open(str(target), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
        warnings: list[dict[str, object]] = []
        if (
            seconds < settings.recommended_reference_min_seconds
            or seconds > settings.recommended_reference_max_seconds
        ):
            warnings.append(
                {
                    "code": "reference_duration_outside_recommended_range",
                    "message": (
                        "Audio file is outside the recommended length of "
                        f"{settings.recommended_reference_min_seconds}-"
                        f"{settings.recommended_reference_max_seconds} seconds."
                    ),
                    "reference_seconds": round(seconds, 3),
                    "recommended_min_seconds": settings.recommended_reference_min_seconds,
                    "recommended_max_seconds": settings.recommended_reference_max_seconds,
                }
            )
        return NormalizedReference(directory, target, seconds, warnings)
    except Exception:
        directory.cleanup()
        raise


def floats_to_pcm(samples) -> bytes:
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    values = np.clip(values, -1.0, 1.0)
    return (values * 32767.0).astype("<i2").tobytes()


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()
