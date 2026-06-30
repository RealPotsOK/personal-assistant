from __future__ import annotations

import io
import json
import wave

from fastapi.testclient import TestClient

from app.config import Settings
from app.core.live import AudioJob
from app.errors import APIError
from app.main import create_app

KEY = "test-shared-key-that-is-long-enough"
AUTH = {"Authorization": f"Bearer {KEY}"}


def wav_bytes(seconds: float = 1.0) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return output.getvalue()


class FakeEngine:
    async def try_load(self):
        return None

    def status(self):
        return {"status": "ready", "model": "whisper-small.en", "loaded": True}

    def validate_request(self, *, language, task):
        if task == "translate":
            raise APIError("Translation requires multilingual small", 400, "unsupported_model_capability")
        if language not in {None, "en", "english"}:
            raise APIError("small.en only supports English", 400, "unsupported_language")
        return "en"

    @staticmethod
    def result(offset=0.0):
        return {
            "text": "hello world",
            "language": "en",
            "language_probability": 0.99,
            "duration": 1.0,
            "duration_after_vad": 1.0,
            "segments": [{"id": 0, "start": offset, "end": offset + 1, "text": "hello world"}],
        }

    async def transcribe(self, _audio, _options, *, offset=0.0):
        return self.result(offset)

    async def transcribe_pcm(self, _audio, _options, *, offset=0.0):
        return self.result(offset)

    async def stream(self, _audio, _options):
        yield {"type": "segment", "data": self.result()["segments"][0]}
        yield {"type": "completed", "data": {"text": "hello world", "language": "en"}}


def make_client(**overrides):
    settings = Settings(
        api_key=KEY,
        model_variant=overrides.pop("model_variant", "small.en"),
        model_id=overrides.pop("model_id", "whisper-small.en"),
        max_audio_seconds=overrides.pop("max_audio_seconds", 10),
        **overrides,
    )
    return TestClient(create_app(settings, FakeEngine(), load_model=False))


def test_auth_and_response_formats():
    audio = wav_bytes()
    with make_client() as client:
        denied = client.post("/v1/audio/transcriptions", files={"file": ("test.wav", audio, "audio/wav")})
        plain = client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("test.wav", audio, "audio/wav")},
            data={"response_format": "text"},
        )
        verbose = client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("test.wav", audio, "audio/wav")},
            data={"response_format": "verbose_json", "word_timestamps": "true"},
        )
    assert denied.status_code == 401
    assert plain.text == "hello world"
    assert verbose.json()["segments"][0]["text"] == "hello world"


def test_generic_upload_mime_is_decoded_by_content():
    with make_client() as client:
        response = client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("recording.wav", wav_bytes(), "application/octet-stream")},
        )
    assert response.status_code == 200
    assert response.json()["text"] == "hello world"


def test_small_en_rejects_translation_and_bad_audio():
    with make_client() as client:
        translated = client.post(
            "/v1/audio/translations",
            headers=AUTH,
            files={"file": ("test.wav", wav_bytes(), "audio/wav")},
        )
        invalid = client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("test.wav", b"not audio", "audio/wav")},
        )
    assert translated.status_code == 400
    assert translated.json()["error"]["code"] == "unsupported_model_capability"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_audio"


def test_model_language_size_and_duration_bounds():
    with make_client(max_audio_bytes=100, max_audio_seconds=1) as client:
        wrong_model = client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("test.wav", wav_bytes(), "audio/wav")},
            data={"model": "something-else"},
        )
        language = client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("test.wav", wav_bytes(), "audio/wav")},
            data={"language": "fr"},
        )
        oversized = client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("test.wav", wav_bytes(), "audio/wav")},
        )
    with make_client(max_audio_seconds=1) as client:
        too_long = client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("test.wav", wav_bytes(1.5), "audio/wav")},
        )
    assert wrong_model.json()["error"]["code"] == "model_not_found"
    assert language.json()["error"]["code"] == "unsupported_language"
    assert oversized.json()["error"]["code"] == "audio_too_large"
    assert too_long.json()["error"]["code"] == "audio_too_long"


def test_sse_segment_stream():
    with make_client() as client:
        response = client.post(
            "/transcribe/stream",
            headers=AUTH,
            files={"file": ("test.wav", wav_bytes(), "audio/wav")},
        )
    assert response.status_code == 200
    assert "event: transcript.segment" in response.text
    assert "event: transcript.completed" in response.text


def test_websocket_partial_and_final(monkeypatch):
    class FakeLiveBuffer:
        def __init__(self, **_kwargs):
            pass

        def feed(self, data):
            return [AudioJob("partial", 1, 1, data, 0.0)]

        def commit(self):
            return AudioJob("final", 1, 2, b"\x00\x00" * 320, 0.0)

    monkeypatch.setattr("app.api.routes.LiveAudioBuffer", FakeLiveBuffer)
    with make_client() as client:
        with client.websocket_connect("/ws/transcribe", headers=AUTH) as socket:
            socket.send_json({"type": "start"})
            assert socket.receive_json()["type"] == "ready"
            socket.send_bytes(b"\x01\x00" * 320)
            socket.send_text(json.dumps({"type": "finish"}))
            partial = socket.receive_json()
            final = socket.receive_json()
            done = socket.receive_json()
    assert partial["type"] == "partial"
    assert final["type"] == "final"
    assert done["type"] == "done"


def test_websocket_validation_and_cancel():
    with make_client() as client:
        with client.websocket_connect("/ws/transcribe", headers=AUTH) as socket:
            socket.send_json({"type": "start", "sample_rate": 48_000})
            error = socket.receive_json()
            assert error["code"] == "invalid_sample_rate"
        with client.websocket_connect("/ws/transcribe", headers=AUTH) as socket:
            socket.send_json({"type": "start"})
            assert socket.receive_json()["type"] == "ready"
            socket.send_text(json.dumps({"type": "cancel"}))
            assert socket.receive_json()["type"] == "cancelled"
