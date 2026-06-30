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
    model_path: str = os.getenv("MODEL_PATH", "/models/whisper")
    model_variant: str = os.getenv("WHISPER_MODEL_VARIANT", "small.en")
    model_id: str = os.getenv("MODEL_ID", "whisper-small.en")
    api_key: str = os.getenv("AI_API_KEY", "")
    device: str = os.getenv("DEVICE", "cuda")
    compute_type: str = os.getenv("COMPUTE_TYPE", "float16")
    max_audio_bytes: int = _integer("MAX_AUDIO_BYTES", 100 * 1024 * 1024, 1)
    max_audio_seconds: int = _integer("MAX_AUDIO_SECONDS", 2 * 60 * 60, 1)
    max_queue: int = _integer("MAX_QUEUE", 4, 0)
    partial_interval_ms: int = _integer("PARTIAL_INTERVAL_MS", 800, 200)
    final_silence_ms: int = _integer("FINAL_SILENCE_MS", 700, 200)
    max_utterance_ms: int = _integer("MAX_UTTERANCE_MS", 28_000, 5_000)
    overlap_ms: int = _integer("OVERLAP_MS", 1_000, 0)

    def validate(self) -> None:
        if len(self.api_key) < 16:
            raise ValueError("AI_API_KEY is required and must be at least 16 characters")
        if self.model_variant not in {"small.en", "small"}:
            raise ValueError("WHISPER_MODEL_VARIANT must be small.en or small")
        if self.device not in {"cuda", "cpu"}:
            raise ValueError("DEVICE must be cuda or cpu")
        if self.compute_type not in {"float16", "int8_float16", "int8", "float32"}:
            raise ValueError("Unsupported COMPUTE_TYPE")
        if self.overlap_ms >= self.max_utterance_ms:
            raise ValueError("OVERLAP_MS must be below MAX_UTTERANCE_MS")


def load_settings() -> Settings:
    settings = Settings()
    settings.validate()
    return settings
