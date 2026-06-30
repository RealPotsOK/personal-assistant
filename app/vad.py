from __future__ import annotations

from collections import deque

import webrtcvad

FRAME_BYTES = 640


class BargeInDetector:
    def __init__(self) -> None:
        self.vad = webrtcvad.Vad(2)
        self.pending = bytearray()
        self.window: deque[bool] = deque(maxlen=5)
        self.latched = False
        self.silence_frames = 0

    def feed(self, pcm: bytes, *, armed: bool) -> bool:
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
                if self.silence_frames >= 25:
                    self.latched = False
                    self.window.clear()
            if armed and not self.latched and len(self.window) == 5 and sum(self.window) >= 3:
                self.latched = True
                triggered = True
        return triggered
