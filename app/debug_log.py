from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings

logger = logging.getLogger("personal_assistant.debug_log")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ConversationLog:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.conversation_log_enabled
        self.path = Path(settings.conversation_log_path)
        self.max_bytes = settings.conversation_log_max_bytes
        self._lock = asyncio.Lock()

    async def write(self, event: str, **fields: Any) -> None:
        if not self.enabled:
            return
        payload = {
            "ts": _now(),
            "event": event,
            **fields,
        }
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        async with self._lock:
            try:
                await asyncio.to_thread(self._append_line, line)
            except OSError as error:
                logger.warning("Conversation log write failed: %s", type(error).__name__)

    def _append_line(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size + len(line.encode("utf-8")) > self.max_bytes:
            rotated = self.path.with_suffix(self.path.suffix + ".1")
            with contextlib.suppress(FileNotFoundError, PermissionError, OSError):
                rotated.unlink()
            with contextlib.suppress(FileNotFoundError, PermissionError, OSError):
                self.path.replace(rotated)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
