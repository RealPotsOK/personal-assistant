from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from app.clients import QwenClient, ServiceHealth, UpstreamError
from app.config import Settings
from app.database import Database
from app.debug_log import ConversationLog
from app.protocol import PayloadKind, ProtocolError, SequenceTracker, decode_frame, encode_frame
from app.screen import ScreenError, ScreenFrame, normalize_screen
from app.text import SentenceChunker, needs_screen
from app.vad import BargeInDetector

logger = logging.getLogger("personal_assistant.session")
PROFILE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_MIC_FRAME_BYTES = 64 * 1024
THINKING = {
    "instant": (384, 0.7, "Respond quickly and directly. Keep the answer concise."),
    "medium": (900, 0.7, "Give a balanced, useful answer without unnecessary detail."),
    "long": (1800, 0.6, "Answer carefully and thoroughly, checking important assumptions."),
}


class SessionRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active = False

    async def acquire(self) -> bool:
        async with self._lock:
            if self._active:
                return False
            self._active = True
            return True

    async def release(self) -> None:
        async with self._lock:
            self._active = False

    @property
    def active(self) -> bool:
        return self._active


@dataclass(slots=True)
class ScreenMetadata:
    explicit: bool = False
    application: str | None = None
    window_title: str | None = None


class AssistantSession:
    def __init__(
        self,
        websocket: WebSocket,
        settings: Settings,
        database: Database,
        qwen: QwenClient,
        health: ServiceHealth,
        conversation_log: ConversationLog | None = None,
        allowed_profile_id: str | None = None,
    ) -> None:
        self.websocket = websocket
        self.settings = settings
        self.database = database
        self.qwen = qwen
        self.health = health
        self.conversation_log = conversation_log or ConversationLog(settings)
        self.allowed_profile_id = allowed_profile_id
        self.send_lock = asyncio.Lock()
        self.whisper = None
        self.whisper_send_lock = asyncio.Lock()
        self.whisper_listener: asyncio.Task | None = None
        self.turn_task: asyncio.Task | None = None
        self.cancel_event = asyncio.Event()
        self.profile_id = ""
        self.voice_id: str | None = None
        self.language = "en"
        self.thinking = "medium"
        self.avatar_state = ""
        self.current_turn_id: str | None = None
        self.sequence = SequenceTracker()
        self.out_sequence = 0
        self.started = time.monotonic()
        self.vad = BargeInDetector(
            vad_mode=settings.barge_in_vad_mode,
            window_frames=settings.barge_in_window_frames,
            trigger_frames=settings.barge_in_trigger_frames,
            reset_silence_frames=settings.barge_in_reset_silence_frames,
        )
        self.barge_in_armed_at = 0.0
        self.latest_screen: ScreenFrame | None = None
        self.screen_metadata: dict[int, ScreenMetadata] = {}
        self.screen_event = asyncio.Event()
        self.background: set[asyncio.Task] = set()
        self.last_final_text = ""
        self.last_final_at = 0.0

    async def send_json(self, payload: dict) -> None:
        async with self.send_lock:
            await self.websocket.send_json(payload)

    async def send_binary(self, payload: bytes, turn_id: str) -> None:
        if turn_id != self.current_turn_id or self.cancel_event.is_set():
            return
        self.out_sequence = (self.out_sequence + 1) & 0xFFFFFFFF
        timestamp = int((time.monotonic() - self.started) * 1000) & 0xFFFFFFFF
        frame = encode_frame(
            PayloadKind.TTS_PCM16,
            payload,
            sequence=self.out_sequence,
            timestamp_ms=timestamp,
        )
        async with self.send_lock:
            await self.websocket.send_bytes(frame)

    async def set_avatar(self, state: str, turn_id: str | None = None) -> None:
        if state == self.avatar_state and turn_id == self.current_turn_id:
            return
        self.avatar_state = state
        await self.send_json(
            {"type": "avatar.state", "state": state, "turn_id": turn_id or self.current_turn_id}
        )

    async def run(self, start: dict) -> None:
        self._configure_start(start)
        self.database.ensure_profile(self.profile_id)
        await self.conversation_log.write(
            "session.started",
            profile_id=self.profile_id,
            thinking=self.thinking,
            language=self.language,
            tts_configured=bool(self.voice_id),
        )
        await self._connect_whisper()
        await self.send_json(
            {
                "type": "session.ready",
                "protocol": 1,
                "profile_id": self.profile_id,
                "audio_in": {"sample_rate": 16_000, "channels": 1, "format": "s16le"},
                "audio_out": {"sample_rate": 24_000, "channels": 1, "format": "s16le"},
                "tts_available": bool(self.voice_id),
            }
        )
        await self.set_avatar("idle")
        try:
            await self._receive_client()
        finally:
            await self.close()

    def _configure_start(self, event: dict) -> None:
        if event.get("type") != "session.start" or event.get("protocol") != 1:
            raise ProtocolError("first event must be session.start with protocol 1")
        profile_id = event.get("profile_id")
        if not isinstance(profile_id, str) or not PROFILE.fullmatch(profile_id):
            raise ProtocolError("profile_id must be 1-64 letters, numbers, dots, dashes, or underscores")
        if self.allowed_profile_id and profile_id != self.allowed_profile_id:
            raise ProtocolError("device token is not authorized for the requested profile_id")
        thinking = event.get("thinking", "medium")
        if thinking not in THINKING:
            raise ProtocolError("thinking must be instant, medium, or long")
        self.profile_id = profile_id
        self.voice_id = event.get("voice_id") or self.settings.default_voice_id
        self.language = str(event.get("language", "en"))
        self.thinking = thinking

    async def _connect_whisper(self) -> None:
        self.whisper = await websockets.connect(
            self.settings.whisper_url,
            additional_headers={"Authorization": f"Bearer {self.settings.ai_api_key}"},
            max_size=self.settings.max_binary_bytes + 1024,
            ping_interval=20,
        )
        await self.whisper.send(
            json.dumps(
                {
                    "type": "start",
                    "sample_rate": 16_000,
                    "channels": 1,
                    "sample_format": "s16le",
                    "language": self.language,
                }
            )
        )
        ready = json.loads(await self.whisper.recv())
        if ready.get("type") != "ready":
            raise UpstreamError(f"Whisper did not become ready: {ready}")
        self.whisper_listener = asyncio.create_task(self._listen_whisper())

    async def _receive_client(self) -> None:
        while True:
            message = await self.websocket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            if message.get("bytes") is not None:
                await self._handle_binary(message["bytes"])
                continue
            if message.get("text") is None:
                continue
            try:
                event = json.loads(message["text"])
            except json.JSONDecodeError as error:
                raise ProtocolError("control frames must contain valid JSON") from error
            await self._handle_control(event)

    async def _handle_binary(self, data: bytes) -> None:
        frame = decode_frame(data, max_payload_bytes=self.settings.max_binary_bytes)
        if frame.kind == PayloadKind.TTS_PCM16:
            raise ProtocolError("clients cannot send TTS audio frames")
        self.sequence.accept(frame)
        if frame.kind == PayloadKind.MIC_PCM16:
            if not frame.payload or len(frame.payload) > MAX_MIC_FRAME_BYTES:
                raise ProtocolError("microphone frame must contain 1-65536 bytes")
            if len(frame.payload) % 2:
                raise ProtocolError("microphone PCM must contain complete 16-bit samples")
            barge_in_armed = (
                self.avatar_state in {"thinking", "speaking"}
                and time.monotonic() >= self.barge_in_armed_at
            )
            if self.vad.feed(frame.payload, armed=barge_in_armed):
                await self.interrupt("barge_in")
            async with self.whisper_send_lock:
                await self.whisper.send(frame.payload)
            return
        if len(frame.payload) > self.settings.max_screen_bytes:
            raise ScreenError("screen frame exceeds the configured byte limit")
        mime = "image/jpeg" if frame.kind == PayloadKind.SCREEN_JPEG else "image/png"
        normalized = await asyncio.to_thread(
            normalize_screen,
            frame.payload,
            mime,
            max_bytes=self.settings.max_screen_bytes,
            max_pixels=self.settings.max_screen_pixels,
        )
        metadata = self.screen_metadata.pop(frame.sequence, ScreenMetadata())
        self.latest_screen = ScreenFrame(
            frame.sequence,
            time.monotonic(),
            mime,
            normalized,
            metadata.explicit,
            metadata.application,
            metadata.window_title,
        )
        self.screen_event.set()

    async def _handle_control(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "ping":
            await self.send_json({"type": "pong", "id": event.get("id")})
        elif kind == "session.update":
            if "thinking" in event:
                if event["thinking"] not in THINKING:
                    raise ProtocolError("thinking must be instant, medium, or long")
                self.thinking = event["thinking"]
            if "voice_id" in event:
                self.voice_id = event["voice_id"] or None
            await self.send_json({"type": "session.updated"})
        elif kind == "screen.metadata":
            sequence = event.get("sequence")
            if not isinstance(sequence, int) or not 0 <= sequence <= 0xFFFFFFFF:
                raise ProtocolError("screen.metadata requires a uint32 sequence")
            self.screen_metadata[sequence] = ScreenMetadata(
                explicit=bool(event.get("explicit", False)),
                application=str(event["application"])[:200] if event.get("application") else None,
                window_title=str(event["window_title"])[:500] if event.get("window_title") else None,
            )
        elif kind == "audio.commit":
            async with self.whisper_send_lock:
                await self.whisper.send(json.dumps({"type": "commit"}))
        elif kind == "interrupt":
            await self.interrupt("client")
        elif kind == "memory.list":
            await self.send_json(
                {"type": "memory.list", "memories": self.database.memories(self.profile_id, limit=100)}
            )
        elif kind == "memory.delete":
            deleted = self.database.delete_memory(self.profile_id, str(event.get("memory_id", "")))
            await self.send_json({"type": "memory.deleted", "deleted": deleted})
        elif kind == "memory.clear":
            self.database.clear_memories(self.profile_id)
            await self.send_json({"type": "memory.cleared"})
        elif kind == "conversation.clear":
            await self.interrupt("conversation_clear")
            self.database.clear_turns(self.profile_id)
            await self.send_json({"type": "conversation.cleared"})
        elif kind == "disconnect":
            await self.websocket.close(code=1000)
        else:
            raise ProtocolError(f"unsupported control event '{kind}'")

    async def _listen_whisper(self) -> None:
        try:
            async for raw in self.whisper:
                if isinstance(raw, bytes):
                    continue
                event = json.loads(raw)
                kind = event.get("type")
                if kind == "partial":
                    await self.set_avatar("listening")
                    await self.send_json(
                        {
                            "type": "transcript.partial",
                            "text": event.get("text", ""),
                            "revision": event.get("revision"),
                        }
                    )
                elif kind == "final":
                    text = str(event.get("text", "")).strip()
                    suppressed_reason = self._suppress_final_reason(text)
                    if suppressed_reason:
                        await self.conversation_log.write(
                            "whisper.suppressed",
                            profile_id=self.profile_id,
                            text=text,
                            reason=suppressed_reason,
                        )
                        await self.send_json(
                            {
                                "type": "transcript.suppressed",
                                "text": text,
                                "reason": suppressed_reason,
                            }
                        )
                    else:
                        await self.send_json({"type": "transcript.final", "text": text})
                    if text and not suppressed_reason:
                        self.last_final_text = text.casefold()
                        self.last_final_at = time.monotonic()
                        await self.conversation_log.write(
                            "whisper.final",
                            profile_id=self.profile_id,
                            text=text,
                        )
                        await self._start_turn(text)
                elif kind == "error":
                    await self.conversation_log.write(
                        "whisper.error",
                        profile_id=self.profile_id,
                        message=str(event.get("message", ""))[:500],
                    )
                    await self.send_json(
                        {"type": "error", "code": "whisper_error", "message": event.get("message")}
                    )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Whisper connection ended: %s", type(error).__name__)
            with contextlib.suppress(Exception):
                await self.send_json(
                    {"type": "error", "code": "whisper_unavailable", "message": "Whisper disconnected"}
                )

    def _suppress_final_reason(self, text: str) -> str | None:
        normalized = " ".join(text.casefold().split())
        if not normalized:
            return "empty"
        if normalized in self.settings.stt_suppressed_finals:
            return "suppressed_phrase"
        if (
            normalized == self.last_final_text
            and time.monotonic() - self.last_final_at <= self.settings.stt_duplicate_window_seconds
        ):
            return "duplicate_final"
        return None

    async def _start_turn(self, transcript: str) -> None:
        if self.turn_task and not self.turn_task.done():
            await self.interrupt("new_utterance")
        self.cancel_event = asyncio.Event()
        turn_id = uuid.uuid4().hex
        self.current_turn_id = turn_id
        self.barge_in_armed_at = time.monotonic() + self.settings.barge_in_grace_seconds
        self.vad.reset()
        self.turn_task = asyncio.create_task(self._run_turn(turn_id, transcript, self.cancel_event))

    async def _screen_for_turn(self, transcript: str, turn_id: str) -> ScreenFrame | None:
        explicit = bool(self.latest_screen and self.latest_screen.explicit)
        if not needs_screen(transcript, explicit=explicit):
            return None
        if self.latest_screen and self.latest_screen.fresh(self.settings.screen_fresh_seconds):
            return self.latest_screen
        self.screen_event.clear()
        await self.send_json({"type": "screen.request", "turn_id": turn_id, "reason": "visual_intent"})
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.screen_event.wait(), self.settings.screen_wait_ms / 1000)
        if self.latest_screen and self.latest_screen.fresh(self.settings.screen_fresh_seconds):
            return self.latest_screen
        await self.send_json(
            {
                "type": "error",
                "code": "screen_unavailable",
                "message": "Continuing without a fresh screen frame",
                "turn_id": turn_id,
            }
        )
        return None

    def _messages(self, transcript: str, memories: list[dict], screen: ScreenFrame | None) -> list[dict]:
        _, _, instruction = THINKING[self.thinking]
        memory_text = "\n".join(f"- {item['content']}" for item in memories) or "- None"
        messages: list[dict] = [
            {
                "role": "system",
                "content": (
                    "You are a private voice assistant. Respond naturally for spoken delivery. "
                    f"{instruction} Use memories only when relevant.\nMemories:\n{memory_text}"
                ),
            }
        ]
        for turn in self.database.recent_turns(self.profile_id):
            messages.append({"role": "user", "content": turn["user_text"]})
            messages.append({"role": "assistant", "content": turn["assistant_text"]})
        if screen:
            context = ""
            if screen.application or screen.window_title:
                context = (
                    f"\nScreen metadata: application={screen.application!r}, "
                    f"title={screen.window_title!r}"
                )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": transcript + context},
                        {"type": "image_url", "image_url": {"url": screen.data_url()}},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": transcript})
        return messages

    async def _run_turn(self, turn_id: str, transcript: str, cancel: asyncio.Event) -> None:
        qwen_done = asyncio.Event()
        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=16)
        tts_task: asyncio.Task | None = None
        answer: list[str] = []
        try:
            await self.set_avatar("thinking", turn_id)
            memories = self.database.memories(self.profile_id, query=transcript, limit=12)
            await self.send_json(
                {"type": "memory.used", "turn_id": turn_id, "memories": memories}
            )
            screen = await self._screen_for_turn(transcript, turn_id)
            messages = self._messages(transcript, memories, screen)
            max_tokens, temperature, _ = THINKING[self.thinking]
            chunker = SentenceChunker(self.settings.max_sentence_chars)
            tts_task = asyncio.create_task(
                self._tts_worker(turn_id, sentence_queue, cancel, qwen_done)
            )
            sources_sent = False
            async for event in self.qwen.stream(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                cancel=cancel,
            ):
                if cancel.is_set() or turn_id != self.current_turn_id:
                    return
                if event.get("web_sources") and not sources_sent:
                    await self.send_json(
                        {"type": "sources", "turn_id": turn_id, "sources": event["web_sources"]}
                    )
                    sources_sent = True
                choices = event.get("choices") or []
                delta = choices[0].get("delta", {}).get("content", "") if choices else ""
                if not delta:
                    continue
                answer.append(delta)
                await self.send_json({"type": "assistant.delta", "turn_id": turn_id, "text": delta})
                for sentence in chunker.feed(delta):
                    await sentence_queue.put(sentence)
            for sentence in chunker.flush():
                await sentence_queue.put(sentence)
            qwen_done.set()
            await sentence_queue.put(None)
            text = "".join(answer).strip()
            if cancel.is_set() or turn_id != self.current_turn_id:
                return
            await self.send_json({"type": "assistant.completed", "turn_id": turn_id, "text": text})
            if tts_task:
                await tts_task
            if cancel.is_set() or turn_id != self.current_turn_id:
                return
            if text:
                self.database.add_turn(self.profile_id, transcript, text)
                await self.conversation_log.write(
                    "qwen.completed",
                    profile_id=self.profile_id,
                    turn_id=turn_id,
                    transcript=transcript,
                    response=text,
                )
                task = asyncio.create_task(self._extract_memories(transcript, text))
                self.background.add(task)
                task.add_done_callback(self.background.discard)
            await self.set_avatar("idle", turn_id)
        except asyncio.CancelledError:
            cancel.set()
            if tts_task:
                tts_task.cancel()
                await asyncio.gather(tts_task, return_exceptions=True)
            raise
        except Exception as error:
            qwen_done.set()
            if tts_task:
                tts_task.cancel()
                await asyncio.gather(tts_task, return_exceptions=True)
            logger.warning("Turn failed: %s", type(error).__name__)
            await self.conversation_log.write(
                "turn.failed",
                profile_id=self.profile_id,
                turn_id=turn_id,
                transcript=transcript,
                error=str(error)[:500],
            )
            if turn_id == self.current_turn_id and not cancel.is_set():
                await self.send_json(
                    {
                        "type": "error",
                        "code": "turn_failed",
                        "message": str(error)[:300],
                        "turn_id": turn_id,
                    }
                )
                await self.set_avatar("idle", turn_id)

    async def _tts_worker(
        self,
        turn_id: str,
        queue: asyncio.Queue[str | None],
        cancel: asyncio.Event,
        qwen_done: asyncio.Event,
    ) -> None:
        first = await queue.get()
        if first is None:
            return
        if not self.voice_id:
            await self._tts_unavailable(turn_id, "No XTTS voice_id is configured")
            await self._discard_sentences(queue)
            return
        status = await self.health.xtts()
        if not status.get("loaded"):
            await self._tts_unavailable(turn_id, "XTTS is unavailable; continuing with text only")
            await self._discard_sentences(queue)
            return
        free = int(status.get("free_vram_bytes", self.settings.min_xtts_free_vram))
        if free < self.settings.min_xtts_free_vram and not qwen_done.is_set():
            buffered = [first]
            while (item := await queue.get()) is not None:
                buffered.append(item)
            status = await self.health.xtts()
            free = int(status.get("free_vram_bytes", 0))
            if free < self.settings.min_xtts_free_vram:
                await self._tts_unavailable(turn_id, "Insufficient GPU capacity for XTTS")
                return
            first = buffered[0]
            queue = asyncio.Queue()
            for item in buffered[1:]:
                queue.put_nowait(item)
            queue.put_nowait(None)
        try:
            async with websockets.connect(
                self.settings.xtts_url,
                additional_headers={"Authorization": f"Bearer {self.settings.ai_api_key}"},
                max_size=self.settings.max_binary_bytes + 1024,
            ) as socket:
                await socket.send(
                    json.dumps(
                        {
                            "type": "start",
                            "voice_id": self.voice_id,
                            "language": self.language,
                        }
                    )
                )
                ready = json.loads(await socket.recv())
                if ready.get("type") != "ready":
                    raise UpstreamError(f"XTTS did not become ready: {ready}")
                await self.send_json(
                    {
                        "type": "audio.start",
                        "turn_id": turn_id,
                        "sample_rate": 24_000,
                        "channels": 1,
                        "format": "s16le",
                    }
                )

                async def send_text() -> None:
                    item: str | None = first
                    while item is not None and not cancel.is_set():
                        await socket.send(json.dumps({"type": "text_delta", "text": item + " "}))
                        item = await queue.get()
                    await socket.send(json.dumps({"type": "cancel" if cancel.is_set() else "finish"}))

                sender = asyncio.create_task(send_text())
                try:
                    async for raw in socket:
                        if cancel.is_set() or turn_id != self.current_turn_id:
                            break
                        if isinstance(raw, bytes):
                            if self.avatar_state != "speaking":
                                await self.set_avatar("speaking", turn_id)
                            await self.send_binary(raw, turn_id)
                            continue
                        event = json.loads(raw)
                        if event.get("type") in {"done", "cancelled"}:
                            break
                        if event.get("type") == "error":
                            raise UpstreamError(event.get("message", "XTTS failed"))
                finally:
                    if not sender.done():
                        sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
                if not cancel.is_set() and turn_id == self.current_turn_id:
                    await self.send_json({"type": "audio.end", "turn_id": turn_id})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("XTTS unavailable: %s", type(error).__name__)
            await self._tts_unavailable(turn_id, "XTTS streaming failed; continuing with text only")
            await self._discard_sentences(queue)

    @staticmethod
    async def _discard_sentences(queue: asyncio.Queue[str | None]) -> None:
        while await queue.get() is not None:
            pass

    async def _tts_unavailable(self, turn_id: str, message: str) -> None:
        if turn_id == self.current_turn_id and not self.cancel_event.is_set():
            await self.conversation_log.write(
                "tts.unavailable",
                profile_id=self.profile_id,
                turn_id=turn_id,
                message=message,
            )
            await self.send_json(
                {"type": "error", "code": "tts_unavailable", "message": message, "turn_id": turn_id}
            )

    async def _extract_memories(self, user_text: str, assistant_text: str) -> None:
        try:
            raw = await self.qwen.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Extract only durable user-provided preferences or personal facts useful in "
                            "future conversations. Return a JSON array of at most 3 short strings. "
                            "Return [] if there are none. JSON only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"USER:\n{user_text}\n\nASSISTANT (context only):\n{assistant_text}",
                    },
                ]
            )
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            values = json.loads(raw)
            added = []
            if isinstance(values, list):
                for value in values[:3]:
                    memory = (
                        self.database.add_memory(self.profile_id, value)
                        if isinstance(value, str)
                        else None
                    )
                    if memory:
                        added.append(memory)
            if added:
                with contextlib.suppress(Exception):
                    await self.send_json({"type": "memory.updated", "memories": added})
        except Exception as error:
            logger.info("Memory extraction skipped: %s", type(error).__name__)

    async def interrupt(self, reason: str) -> None:
        if not self.current_turn_id or not self.turn_task or self.turn_task.done():
            return
        turn_id = self.current_turn_id
        self.cancel_event.set()
        await self.conversation_log.write(
            "turn.interrupted",
            profile_id=self.profile_id,
            turn_id=turn_id,
            reason=reason,
        )
        await self.send_json({"type": "playback.cancel", "turn_id": turn_id, "reason": reason})
        self.turn_task.cancel()
        await asyncio.gather(self.turn_task, return_exceptions=True)
        self.current_turn_id = None
        self.vad.reset()
        await self.set_avatar("listening")

    async def close(self) -> None:
        if self.turn_task and not self.turn_task.done():
            self.cancel_event.set()
            self.turn_task.cancel()
            await asyncio.gather(self.turn_task, return_exceptions=True)
        if self.whisper_listener:
            self.whisper_listener.cancel()
            await asyncio.gather(self.whisper_listener, return_exceptions=True)
        if self.whisper:
            with contextlib.suppress(Exception):
                await self.whisper.close()
        if self.profile_id:
            await self.conversation_log.write("session.closed", profile_id=self.profile_id)
