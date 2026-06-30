from __future__ import annotations

import os
from dataclasses import dataclass


def _integer(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    client_token: str = os.getenv("PA_CLIENT_TOKEN", "")
    qwen_url: str = os.getenv("QWEN_URL", "http://host.docker.internal:11111")
    qwen_model: str = os.getenv("QWEN_MODEL", "qwen3-vl-8b-instruct")
    whisper_url: str = os.getenv("WHISPER_URL", "ws://host.docker.internal:11113/ws/transcribe")
    xtts_url: str = os.getenv("XTTS_URL", "ws://host.docker.internal:11112/ws/tts")
    xtts_http_url: str = os.getenv("XTTS_HTTP_URL", "http://host.docker.internal:11112")
    default_voice_id: str | None = os.getenv("DEFAULT_XTTS_VOICE_ID") or None
    database_path: str = os.getenv("DATABASE_PATH", "/data/personal-assistant.sqlite")
    max_binary_bytes: int = _integer("MAX_BINARY_BYTES", 5 * 1024 * 1024, 1024)
    max_screen_bytes: int = _integer("MAX_SCREEN_BYTES", 5 * 1024 * 1024, 1024)
    max_screen_pixels: int = _integer("MAX_SCREEN_PIXELS", 1_048_576, 65_536)
    screen_fresh_seconds: int = _integer("SCREEN_FRESH_SECONDS", 10, 1)
    screen_wait_ms: int = _integer("SCREEN_WAIT_MS", 750, 0)
    max_turns: int = _integer("MAX_PROFILE_TURNS", 24, 1)
    max_memories: int = _integer("MAX_PROFILE_MEMORIES", 100, 1)
    max_sentence_chars: int = _integer("MAX_SENTENCE_CHARS", 240, 32)
    min_xtts_free_vram: int = _integer("MIN_XTTS_FREE_VRAM_BYTES", 2 * 1024**3, 0)
    upstream_timeout: int = _integer("UPSTREAM_TIMEOUT_SECONDS", 30, 1)
    pairing_enabled: bool = os.getenv("PAIRING_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    pairing_rate_limit_per_minute: int = _integer("PAIRING_RATE_LIMIT_PER_MINUTE", 5, 1)
    max_voice_reference_bytes: int = _integer("MAX_VOICE_REFERENCE_BYTES", 20 * 1024 * 1024, 1024)
    conversation_log_enabled: bool = os.getenv("CONVERSATION_LOG_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    conversation_log_path: str = os.getenv("CONVERSATION_LOG_PATH", "/logs/conversation.log")
    conversation_log_max_bytes: int = _integer("CONVERSATION_LOG_MAX_BYTES", 10 * 1024 * 1024, 1024)

    def validate(self) -> None:
        if len(self.ai_api_key) < 16:
            raise ValueError("AI_API_KEY is required and must be at least 16 characters")
        if len(self.client_token) < 16:
            raise ValueError("PA_CLIENT_TOKEN is required and must be at least 16 characters")


def load_settings() -> Settings:
    settings = Settings()
    settings.validate()
    return settings
