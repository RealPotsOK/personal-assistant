import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatCompletionRequest


def test_accepts_openai_multimodal_message() -> None:
    request = ChatCompletionRequest.model_validate(
        {
            "model": "qwen3-vl-8b-instruct",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe it"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,AAAA"},
                        },
                    ],
                }
            ],
        }
    )
    assert request.messages[0].role == "user"
    assert request.requested_max_tokens(512) == 512


def test_rejects_images_in_assistant_message() -> None:
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate(
            {
                "model": "qwen3-vl-8b-instruct",
                "messages": [
                    {"role": "user", "content": "Earlier"},
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.com/a.png"},
                            }
                        ],
                    },
                ],
            }
        )


def test_rejects_both_token_limit_fields() -> None:
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate(
            {
                "model": "qwen3-vl-8b-instruct",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 10,
                "max_completion_tokens": 10,
            }
        )
