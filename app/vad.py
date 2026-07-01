from __future__ import annotations

from collections import deque

import webrtcvad

FRAME_BYTES = 640


class BargeInDetector:
    def __init__(
        self,
        *,
        vad_mode: int = 3,
        window_frames: int = 12,
        trigger_frames: int = 10,
        reset_silence_frames: int = 25,
    ) -> None:
        self.vad = webrtcvad.Vad(vad_mode)
        self.pending = bytearray()
        self.window: deque[bool] = deque(maxlen=window_frames)
        self.latched = False
        self.silence_frames = 0
        self.trigger_frames = trigger_frames
        self.reset_silence_frames = reset_silence_frames

    def reset(self) -> None:
        self.pending.clear()
        self.window.clear()
        self.latched = False
        self.silence_frames = 0

    def feed(self, pcm: bytes, *, armed: bool) -> bool:
        if not armed:
            self.reset()
            return False
        self.pending.extend(pcm)
        triggered = False
        while len(self.pending) >= FRAME_BYTES:
            frame = bytes(self.pending[:FRAME_BYTES])
            del self.pending[:FRAME_BYTES]
            voiced = self.vad.is_speech(frame, 16_000)
            self.window.append(voiced)
            if voiced:
                self.silence_frames = 0
            else:
                self.silence_frames += 1
                if self.silence_frames >= self.reset_silence_frames:
                    self.latched = False
                    self.window.clear()
            if (
                not self.latched
                and len(self.window) == self.window.maxlen
                and sum(self.window) >= self.trigger_frames
            ):
                self.latched = True
                triggered = True
        return triggered
