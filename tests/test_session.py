import asyncio
import time

from app.config import Settings
from app.database import Database
from app.screen import ScreenFrame
from app.session import AssistantSession


class FakeWebSocket:
    def __init__(self):
        self.json = []
        self.binary = []

    async def send_json(self, value):
        self.json.append(value)

    async def send_bytes(self, value):
        self.binary.append(value)


class FakeHealth:
    async def xtts(self):
        return {"loaded": False}


class FakeQwen:
    pass


def make_session(tmp_path):
    config = Settings(
        ai_api_key="test-internal-ai-key-that-is-long-enough",
        client_token="test-pc-client-token-that-is-long-enough",
        database_path=str(tmp_path / "session.sqlite"),
        conversation_log_path=str(tmp_path / "conversation.log"),
    )
    database = Database(config.database_path)
    socket = FakeWebSocket()
    session = AssistantSession(socket, config, database, FakeQwen(), FakeHealth())
    session.profile_id = "pc"
    session.database.ensure_profile("pc")
    return session, socket, database


def test_prompt_contains_recent_history_memory_and_screen(tmp_path):
    session, _, database = make_session(tmp_path)
    database.add_turn("pc", "Earlier question", "Earlier answer")
    memory = database.add_memory("pc", "User likes green tea")
    screen = ScreenFrame(
        1,
        time.monotonic(),
        "image/jpeg",
        b"image",
        application="Editor",
        window_title="main.py",
    )
    messages = session._messages("What is this?", [memory], screen)
    assert "User likes green tea" in messages[0]["content"]
    assert messages[1:3] == [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    ]
    assert messages[-1]["content"][1]["type"] == "image_url"
    database.close()


async def test_interrupt_cancels_active_turn_and_marks_playback(tmp_path):
    session, socket, database = make_session(tmp_path)
    session.current_turn_id = "turn-1"
    session.avatar_state = "speaking"
    session.turn_task = asyncio.create_task(asyncio.sleep(30))
    await session.interrupt("barge_in")
    assert session.cancel_event.is_set()
    assert session.turn_task.cancelled()
    assert socket.json[0] == {
        "type": "playback.cancel",
        "turn_id": "turn-1",
        "reason": "barge_in",
    }
    assert socket.json[-1]["state"] == "listening"
    database.close()


async def test_unavailable_tts_drains_bounded_sentence_queue(tmp_path):
    session, socket, database = make_session(tmp_path)
    session.current_turn_id = "turn-1"
    queue = asyncio.Queue(maxsize=1)
    await queue.put("First sentence.")
    worker = asyncio.create_task(
        session._tts_worker("turn-1", queue, session.cancel_event, asyncio.Event())
    )
    await asyncio.sleep(0)
    await queue.put(None)
    await asyncio.wait_for(worker, 1)
    assert any(event.get("code") == "tts_unavailable" for event in socket.json)
    database.close()


def test_suppresses_common_short_whisper_hallucinations_and_duplicates(tmp_path):
    session, _, database = make_session(tmp_path)
    assert session._suppress_final_reason("Thank you.") == "suppressed_phrase"
    assert session._suppress_final_reason("You") == "suppressed_phrase"
    assert session._suppress_final_reason("Actual question?") is None
    session.last_final_text = "actual question?"
    session.last_final_at = time.monotonic()
    assert session._suppress_final_reason("Actual question?") == "duplicate_final"
    database.close()
