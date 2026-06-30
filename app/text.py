from __future__ import annotations

import re

VISUAL_INTENT = re.compile(
    r"\b(?:this|that|these|those|screen|screenshot|window|image|picture|looking at|see here|"
    r"on my (?:screen|monitor)|what(?:'s| is) this)\b",
    re.IGNORECASE,
)
BOUNDARY = re.compile(r"(?<=[.!?])(?:[\"'”’)]*)\s+")
ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "e.g.", "i.e.", "vs.", "etc."}


def needs_screen(text: str, *, explicit: bool = False) -> bool:
    return explicit or bool(VISUAL_INTENT.search(text))


class SentenceChunker:
    def __init__(self, max_chars: int = 240) -> None:
        self.max_chars = max_chars
        self.buffer = ""

    def feed(self, delta: str) -> list[str]:
        self.buffer += delta
        output: list[str] = []
        while True:
            match = BOUNDARY.search(self.buffer)
            if match:
                candidate = self.buffer[: match.end()].strip()
                last_word = candidate.lower().split()[-1].strip('\"\'”’)') if candidate.split() else ""
                if last_word in ABBREVIATIONS:
                    next_start = match.end()
                    next_match = BOUNDARY.search(self.buffer, next_start)
                    if not next_match:
                        break
                    match = next_match
                    candidate = self.buffer[: match.end()].strip()
                output.extend(self._split(candidate))
                self.buffer = self.buffer[match.end() :]
                continue
            if len(self.buffer) >= self.max_chars:
                split_at = self.buffer.rfind(" ", 0, self.max_chars + 1)
                split_at = split_at if split_at > 0 else self.max_chars
                output.append(self.buffer[:split_at].strip())
                self.buffer = self.buffer[split_at:].lstrip()
                continue
            break
        return [item for item in output if item]

    def flush(self) -> list[str]:
        value = self.buffer.strip()
        self.buffer = ""
        return self._split(value) if value else []

    def _split(self, value: str) -> list[str]:
        parts: list[str] = []
        while len(value) > self.max_chars:
            split_at = value.rfind(" ", 0, self.max_chars + 1)
            split_at = split_at if split_at > 0 else self.max_chars
            parts.append(value[:split_at].strip())
            value = value[split_at:].strip()
        if value:
            parts.append(value)
        return parts
