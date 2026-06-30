from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImageURL(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    detail: Literal["auto", "low", "high"] | None = None


class TextPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: str


class ImageURLPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["image_url"]
    image_url: ImageURL


ContentPart = Annotated[TextPart | ImageURLPart, Field(discriminator="type")]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str | list[ContentPart]

    @model_validator(mode="after")
    def validate_content(self) -> "ChatMessage":
        if isinstance(self.content, list):
            if not self.content:
                raise ValueError("message content cannot be empty")
            if self.role != "user" and any(isinstance(part, ImageURLPart) for part in self.content):
                raise ValueError("images are only supported in user messages")
        return self


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    stream: bool = False

    @model_validator(mode="after")
    def validate_request(self) -> "ChatCompletionRequest":
        if self.max_tokens is not None and self.max_completion_tokens is not None:
            raise ValueError("provide max_tokens or max_completion_tokens, not both")
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("at least one user message is required")
        return self

    def requested_max_tokens(self, default: int) -> int:
        return self.max_completion_tokens or self.max_tokens or default
