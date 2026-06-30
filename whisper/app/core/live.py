from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import webrtcvad

SAMPLE_RATE = 16_000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2


@dataclass(slots=True)
class AudioJob:
    kind: str
    utterance_id: int
    revision: int
    pcm: bytes
    offset_seconds: float
    forced: bool = False


def remove_word_overlap(previous: str, current: str, limit: int = 20) -> str:
    before = previous.strip().split()
    after = current.strip().split()
    for length in range(min(limit, len(before), len(after)), 0, -1):
        if [word.lower() for word in before[-length:]] == [word.lower() for word in after[:length]]:
            return " ".join(after[length:]).strip()
    return current.strip()


class LiveAudioBuffer:
    def __init__(
        self,
        *,
        partial_interval_ms: int,
        final_silence_ms: int,
        max_utterance_ms: int,
        overlap_ms: int,
    ) -> None:
        self.vad = webrtcvad.Vad(2)
        self.partial_interval_ms = partial_interval_ms
        self.final_silence_ms = final_silence_ms
        self.max_utterance_ms = max_utterance_ms
        self.overlap_ms = overlap_ms
        self.pending = bytearray()
        self.pre_roll: deque[bytes] = deque(maxlen=15)
        self.voice_window: deque[bool] = deque(maxlen=5)
        self.utterance = bytearray()
        self.in_speech = False
        self.silence_ms = 0
        self.since_partial_ms = 0
        self.total_ms = 0
        self.start_ms = 0
        self.utterance_id = 0
        self.revision = 0

    def _start(self) -> None:
        self.in_speech = True
        self.utterance_id += 1
        self.revision = 0
        self.silence_ms = 0
        self.since_partial_ms = 0
        self.start_ms = max(0, self.total_ms - len(self.pre_roll) * FRAME_MS)
        self.utterance = bytearray().join(self.pre_roll)

    def _job(self, kind: str, forced: bool = False) -> AudioJob:
        self.revision += 1
        return AudioJob(
            kind,
            self.utterance_id,
            self.revision,
            bytes(self.utterance),
            self.start_ms / 1000,
            forced,
        )

    def _reset(self, overlap: bytes = b"") -> None:
        self.in_speech = bool(overlap)
        self.utterance = bytearray(overlap)
        self.silence_ms = 0
        self.since_partial_ms = 0
        self.pre_roll.clear()
        self.voice_window.clear()
        if overlap:
            self.utterance_id += 1
            self.revision = 0
            self.start_ms = max(0, self.total_ms - self.overlap_ms)

    def feed(self, data: bytes) -> list[AudioJob]:
        self.pending.extend(data)
        jobs: list[AudioJob] = []
        while len(self.pending) >= FRAME_BYTES:
            frame = bytes(self.pending[:FRAME_BYTES])
            del self.pending[:FRAME_BYTES]
            self.total_ms += FRAME_MS
            voiced = self.vad.is_speech(frame, SAMPLE_RATE)
            if not self.in_speech:
                self.pre_roll.append(frame)
                self.voice_window.append(voiced)
                if len(self.voice_window) == self.voice_window.maxlen and sum(self.voice_window) >= 3:
                    self._start()
                continue

            self.utterance.extend(frame)
            self.since_partial_ms += FRAME_MS
            self.silence_ms = 0 if voiced else self.silence_ms + FRAME_MS
            duration_ms = len(self.utterance) // 2 * 1000 // SAMPLE_RATE
            if self.since_partial_ms >= self.partial_interval_ms:
                jobs.append(self._job("partial"))
                self.since_partial_ms = 0
            if self.silence_ms >= self.final_silence_ms:
                jobs.append(self._job("final"))
                self._reset()
            elif duration_ms >= self.max_utterance_ms:
                jobs.append(self._job("final", forced=True))
                overlap_bytes = SAMPLE_RATE * self.overlap_ms // 1000 * 2
                self._reset(bytes(self.utterance[-overlap_bytes:]) if overlap_bytes else b"")
        return jobs

    def commit(self) -> AudioJob | None:
        if not self.utterance:
            return None
        job = self._job("final")
        self._reset()
        return job
