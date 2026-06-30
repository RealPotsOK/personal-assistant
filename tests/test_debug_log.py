import json

from app.config import Settings
from app.debug_log import ConversationLog


async def test_conversation_log_writes_jsonl(tmp_path):
    settings = Settings(
        ai_api_key="test-internal-ai-key-that-is-long-enough",
        client_token="test-pc-client-token-that-is-long-enough",
        conversation_log_path=str(tmp_path / "conversation.log"),
    )
    log = ConversationLog(settings)

    await log.write("whisper.final", profile_id="pc", text="hello")
    await log.write("qwen.completed", profile_id="pc", response="hi there")

    lines = (tmp_path / "conversation.log").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == [
        "whisper.final",
        "qwen.completed",
    ]
    assert json.loads(lines[0])["text"] == "hello"
