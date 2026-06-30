from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.config import settings
from app.core.inference import GenerationResult
from app.core.messages import prepare_messages
from app.main import create_app
from app.schemas.chat import ChatCompletionRequest


AUTH = {"Authorization": f"Bearer {settings.api_key}"}


class FakeEngine:
    ready = True
    load_error = None

    async def generate(self, messages, **kwargs) -> GenerationResult:
        return GenerationResult("Hello from Qwen", 8, 3)

    async def stream(self, messages, **kwargs) -> AsyncIterator[str]:
        yield "Hello "
        yield "from Qwen"


def make_client() -> TestClient:
    return TestClient(create_app(settings, FakeEngine(), load_model=False))


def test_models_and_health() -> None:
    with make_client() as client:
        assert client.get("/health").json()["status"] == "ready"
        assert client.get("/v1/models", headers=AUTH).json()["data"][0]["id"] == settings.model_id


def test_non_streaming_completion() -> None:
    with make_client() as client:
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "model": settings.model_id,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "Hello from Qwen"
    assert body["usage"]["total_tokens"] == 11
    assert body["web_sources"] == []


def test_streaming_completion() -> None:
    with make_client() as client:
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "model": settings.model_id,
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
    assert response.status_code == 200
    assert '"content":"Hello "' in response.text
    assert '"finish_reason":"stop"' in response.text
    assert "data: [DONE]" in response.text


def test_openai_style_validation_error() -> None:
    with make_client() as client:
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"model": settings.model_id, "messages": []},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_model_is_rejected() -> None:
    with make_client() as client:
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"model": "other", "messages": [{"role": "user", "content": "Hi"}]},
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"


def test_model_routes_require_authentication() -> None:
    with make_client() as client:
        response = client.get("/v1/models")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_text_messages_are_normalized_for_multimodal_processor() -> None:
    request = ChatCompletionRequest.model_validate(
        {
            "model": settings.model_id,
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Hello"},
            ],
        }
    )
    messages, sources = await prepare_messages(request, settings)
    assert sources == []
    assert messages[0]["content"][0]["type"] == "text"
    assert messages[1]["content"] == [{"type": "text", "text": "Hello"}]


async def test_inserted_safety_system_message_uses_multimodal_content_shape() -> None:
    request = ChatCompletionRequest.model_validate(
        {
            "model": settings.model_id,
            "messages": [{"role": "user", "content": "Hello"}],
        }
    )
    messages, _ = await prepare_messages(request, settings)
    assert messages[0]["role"] == "system"
    assert messages[0]["content"][0]["type"] == "text"
