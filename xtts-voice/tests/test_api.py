from __future__ import annotations

import io
import wave
from types import SimpleNamespace

import torch
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

KEY = "test-api-key-that-is-long-enough"
AUTH = {"Authorization": f"Bearer {KEY}"}


class FakeEngine:
    def __init__(self):
        self.config = SimpleNamespace(languages=["en", "es"])

    async def ensure_loaded(self):
        return None

    async def try_load(self):
        return None

    def status(self):
        return {"status": "ready", "model": "xtts-v2", "device": "cuda", "loaded": True}

    async def condition(self, _path):
        return torch.ones((1, 2, 3)), torch.ones((1, 512, 1))

    async def synthesize(self, _text, _language, _conditioning, _embedding):
        return b"\x00\x00" * 240

    async def stream(self, _text, _language, _conditioning, _embedding):
        yield b"\x01\x00" * 12
        yield b"\x02\x00" * 12

    async def stream_segment(self, _text, _language, _conditioning, _embedding):
        yield b"\x01\x00" * 12


class FakeStore:
    def __init__(self):
        self.conditioning = torch.ones((1, 2, 3))
        self.embedding = torch.ones((1, 512, 1))

    def get(self, voice_id):
        if voice_id != "voice_test":
            from app.errors import APIError

            raise APIError("Voice not found", 404, "voice_not_found")
        return self.conditioning, self.embedding

    def list(self):
        return []

    def save(self, *_args, **_kwargs):
        return {
            "voice_id": "voice_test",
            "name": None,
            "model": "xtts-v2",
            "created_at": "2026-01-01T00:00:00+00:00",
            "reference_seconds": 4.0,
        }

    def delete(self, _voice_id):
        return None


def client(max_text_chars=5000):
    settings = Settings(
        api_key=KEY,
        voice_dir="/tmp/test-voices",
        max_text_chars=max_text_chars,
        min_reference_seconds=3,
        max_reference_seconds=30,
    )
    app = create_app(settings, FakeEngine(), FakeStore(), load_model=False)
    return TestClient(app)


def wav_bytes(seconds: int, sample_rate: int = 24_000) -> bytes:
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * (sample_rate * seconds))
    return audio.getvalue()


def test_auth_is_required():
    with client() as api:
        response = api.post("/tts", json={"text": "Hello", "voice_id": "voice_test"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_complete_and_streaming_audio():
    with client() as api:
        complete = api.post(
            "/tts", headers=AUTH, json={"text": "Hello", "voice_id": "voice_test", "language": "en"}
        )
        streamed = api.post(
            "/tts/stream",
            headers=AUTH,
            json={"text": "Hello", "voice_id": "voice_test", "language": "en"},
        )
    assert complete.status_code == 200
    assert complete.headers["content-type"].startswith("audio/wav")
    assert complete.content.startswith(b"RIFF")
    assert streamed.status_code == 200
    assert streamed.headers["x-audio-sample-rate"] == "24000"
    assert streamed.content == b"\x01\x00" * 12 + b"\x02\x00" * 12


def test_openai_alias_validation_and_text_limit():
    with client(max_text_chars=5) as api:
        too_long = api.post("/tts", headers=AUTH, json={"text": "too long", "voice_id": "voice_test"})
        speed = api.post(
            "/v1/audio/speech",
            headers=AUTH,
            json={"model": "xtts-v2", "input": "Hi", "voice": "voice_test", "speed": 1.2},
        )
    assert too_long.status_code == 400
    assert too_long.json()["error"]["code"] == "text_too_long"
    assert speed.status_code == 400
    assert speed.json()["error"]["code"] == "unsupported_value"


def test_reference_upload_is_normalized_for_voice_cache():
    with client() as api:
        response = api.post(
            "/voices/cache",
            headers=AUTH,
            files={"reference_audio": ("voice.wav", wav_bytes(24), "audio/wav")},
            data={"name": "Test voice"},
        )
    assert response.status_code == 201
    assert response.json()["voice_id"] == "voice_test"
    assert "warnings" not in response.json()


def test_short_reference_upload_saves_with_duration_warning():
    with client() as api:
        response = api.post(
            "/voices/cache",
            headers=AUTH,
            files={"reference_audio": ("voice.wav", wav_bytes(4), "audio/wav")},
            data={"name": "Short voice"},
        )
    assert response.status_code == 201
    payload = response.json()
    assert payload["voice_id"] == "voice_test"
    assert payload["warnings"][0]["code"] == "reference_duration_outside_recommended_range"
    assert payload["warnings"][0]["reference_seconds"] == 4.0


def test_long_reference_upload_saves_with_duration_warning():
    with client() as api:
        response = api.post(
            "/voices/cache",
            headers=AUTH,
            files={"reference_audio": ("voice.wav", wav_bytes(31), "audio/wav")},
            data={"name": "Long voice"},
        )
    assert response.status_code == 201
    payload = response.json()
    assert payload["voice_id"] == "voice_test"
    assert payload["warnings"][0]["code"] == "reference_duration_outside_recommended_range"
    assert payload["warnings"][0]["reference_seconds"] == 31.0


def test_websocket_text_in_binary_audio_out():
    with client() as api:
        with api.websocket_connect("/ws/tts", headers=AUTH) as socket:
            socket.send_json({"type": "start", "voice_id": "voice_test", "language": "en"})
            assert socket.receive_json()["type"] == "ready"
            socket.send_json({"type": "text_delta", "text": "Hello there. "})
            socket.send_json({"type": "finish"})
            assert socket.receive_json() == {"type": "segment_start", "index": 1}
            assert socket.receive_bytes() == b"\x01\x00" * 12
            assert socket.receive_json() == {"type": "segment_end", "index": 1}
            assert socket.receive_json() == {"type": "done"}
