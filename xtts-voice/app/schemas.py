from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1)
    voice_id: str = Field(pattern=r"^voice_[A-Za-z0-9_-]+$")
    language: str = "en"

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text cannot be blank")
        return value


class OpenAISpeechRequest(BaseModel):
    model: str = "xtts-v2"
    input: str = Field(min_length=1)
    voice: str = Field(pattern=r"^voice_[A-Za-z0-9_-]+$")
    response_format: str = "wav"
    speed: float = 1.0
    language: str = "en"


class VoiceMetadata(BaseModel):
    voice_id: str
    name: str | None
    model: str
    created_at: str
    reference_seconds: float
    warnings: list[dict] = Field(default_factory=list)
