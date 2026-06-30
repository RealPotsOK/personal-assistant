from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.session import SessionRegistry

TOKEN = "test-pc-client-token-that-is-long-enough"


def settings(tmp_path):
    return Settings(
        ai_api_key="test-internal-ai-key-that-is-long-enough",
        client_token=TOKEN,
        database_path=str(tmp_path / "controller.sqlite"),
        qwen_url="http://127.0.0.1:9",
        whisper_url="ws://127.0.0.1:9/ws/transcribe",
        xtts_url="ws://127.0.0.1:9/ws/tts",
        xtts_http_url="http://127.0.0.1:9",
    )


def test_live_health_and_websocket_auth(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get("/live").status_code == 200
        health = client.get("/health")
        assert health.status_code == 503
        assert health.json()["status"] == "degraded"
        with client.websocket_connect("/session") as socket:
            closed = socket.receive()
        assert closed["type"] == "websocket.close"
        assert closed["code"] == 4401


async def test_single_session_registry():
    registry = SessionRegistry()
    assert await registry.acquire()
    assert not await registry.acquire()
    await registry.release()
    assert await registry.acquire()


def test_pair_revoke_and_device_bound_profile(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        pair = client.post("/pair", json={"device_name": "Kevin Desktop"})
        assert pair.status_code == 201
        payload = pair.json()
        assert payload["profile_id"].startswith("profile-")
        token = payload["device_token"]

        health = client.get("/health")
        assert health.json()["paired_devices"] == 1

        with client.websocket_connect(
            "/session",
            headers={"Authorization": f"Bearer {token}"},
        ) as socket:
            socket.send_json(
                {
                    "type": "session.start",
                    "protocol": 1,
                    "profile_id": "somebody-else",
                    "thinking": "medium",
                }
            )
            assert socket.receive_json()["code"] == "protocol_error"
            assert socket.receive()["type"] == "websocket.close"

        revoked = client.post("/device/revoke-self", headers={"Authorization": f"Bearer {token}"})
        assert revoked.status_code == 200
        assert revoked.json()["revoked"] is True

        with client.websocket_connect(
            "/session",
            headers={"Authorization": f"Bearer {token}"},
        ) as socket:
            closed = socket.receive()
        assert closed["type"] == "websocket.close"
        assert closed["code"] == 4401


def test_setup_voice_reports_xtts_unavailable_for_paired_device(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        token = client.post("/pair", json={"device_name": "Kevin Desktop"}).json()["device_token"]
        response = client.post(
            "/setup/voice",
            headers={"Authorization": f"Bearer {token}"},
            data={"name": "test voice"},
            files={"reference_audio": ("voice.wav", b"RIFFnot-a-real-wav", "audio/wav")},
        )
        assert response.status_code == 503
        assert response.json()["code"] == "xtts_unavailable"
