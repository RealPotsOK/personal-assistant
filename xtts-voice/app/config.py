from __future__ import annotations

import os
from dataclasses import dataclass


def _integer(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    model_path: str = os.getenv("MODEL_PATH", "/models/xtts-v2")
    model_id: str = os.getenv("MODEL_ID", "xtts-v2")
    voice_dir: str = os.getenv("VOICE_DIR", "/data/voices")
    api_key: str = os.getenv("AI_API_KEY", os.getenv("XTTS_API_KEY", ""))
    device: str = os.getenv("DEVICE", "cuda")
    sample_rate: int = _integer("SAMPLE_RATE", 24_000, 8_000)
    max_text_chars: int = _integer("MAX_TEXT_CHARS", 5_000, 1)
    max_reference_bytes: int = _integer("MAX_REFERENCE_BYTES", 20 * 1024 * 1024, 1)
    min_reference_seconds: int = _integer("MIN_REFERENCE_SECONDS", 3, 1)
    max_reference_seconds: int = _integer("MAX_REFERENCE_SECONDS", 30, 1)
    recommended_reference_min_seconds: int = _integer("RECOMMENDED_REFERENCE_MIN_SECONDS", 20, 1)
    recommended_reference_max_seconds: int = _integer("RECOMMENDED_REFERENCE_MAX_SECONDS", 30, 1)
    max_queue: int = _integer("MAX_QUEUE", 8, 0)
    stream_chunk_size: int = _integer("STREAM_CHUNK_SIZE", 20, 1)
    max_segment_chars: int = _integer("MAX_SEGMENT_CHARS", 240, 40)

    def validate(self) -> None:
        if len(self.api_key) < 16:
            raise ValueError("AI_API_KEY is required and must be at least 16 characters")
        if self.device not in {"cuda", "cpu"}:
            raise ValueError("DEVICE must be cuda or cpu")
        if self.min_reference_seconds >= self.max_reference_seconds:
            raise ValueError("MIN_REFERENCE_SECONDS must be below MAX_REFERENCE_SECONDS")
        if self.recommended_reference_min_seconds >= self.recommended_reference_max_seconds:
            raise ValueError(
                "RECOMMENDED_REFERENCE_MIN_SECONDS must be below "
                "RECOMMENDED_REFERENCE_MAX_SECONDS"
            )


def load_settings() -> Settings:
    value = Settings()
    value.validate()
    return value
