from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    model_path: str = os.getenv("MODEL_PATH", "/models/qwen3-vl-8b-instruct")
    model_id: str = os.getenv("MODEL_ID", "qwen3-vl-8b-instruct")
    quantization: str = os.getenv("QUANTIZATION", "4bit").lower()
    attention_implementation: str = os.getenv("ATTENTION_IMPLEMENTATION", "sdpa")
    api_key: str = os.getenv("AI_API_KEY", "")

    default_max_tokens: int = _env_int("DEFAULT_MAX_TOKENS", 512, minimum=1)
    max_tokens: int = _env_int("MAX_TOKENS", 2048, minimum=1)

    max_images: int = _env_int("MAX_IMAGES", 4, minimum=0)
    max_image_bytes: int = _env_int("MAX_IMAGE_BYTES", 10 * 1024 * 1024, minimum=1)
    max_image_pixels: int = _env_int("MAX_IMAGE_PIXELS", 1_048_576, minimum=1)

    max_web_pages: int = _env_int("MAX_WEB_PAGES", 5, minimum=0)
    max_web_depth: int = _env_int("MAX_WEB_DEPTH", 1, minimum=0)
    max_web_page_bytes: int = _env_int("MAX_WEB_PAGE_BYTES", 2 * 1024 * 1024, minimum=1)
    max_web_chars_per_page: int = _env_int("MAX_WEB_CHARS_PER_PAGE", 12_000, minimum=1)
    max_web_total_chars: int = _env_int("MAX_WEB_TOTAL_CHARS", 40_000, minimum=1)
    max_redirects: int = _env_int("MAX_REDIRECTS", 3, minimum=0)
    fetch_timeout_seconds: float = _env_float("FETCH_TIMEOUT_SECONDS", 10.0, minimum=0.1)
    crawl_timeout_seconds: float = _env_float("CRAWL_TIMEOUT_SECONDS", 20.0, minimum=0.1)
    user_agent: str = os.getenv("WEB_USER_AGENT", "Qwen3VLAPI/1.0")

    def validate(self) -> None:
        if len(self.api_key) < 16:
            raise ValueError("AI_API_KEY is required and must be at least 16 characters")
        if self.quantization not in {"8bit", "4bit"}:
            raise ValueError("QUANTIZATION must be either '8bit' or '4bit'")
        if self.default_max_tokens > self.max_tokens:
            raise ValueError("DEFAULT_MAX_TOKENS cannot exceed MAX_TOKENS")
        if self.attention_implementation not in {"sdpa", "flash_attention_2", "eager"}:
            raise ValueError("ATTENTION_IMPLEMENTATION must be sdpa, flash_attention_2, or eager")


settings = Settings()
settings.validate()
