from __future__ import annotations

import re

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+")


def split_text(text: str, max_chars: int = 240) -> list[str]:
    text = " ".join(text.strip().split())
    if not text:
        return []
    result: list[str] = []
    for sentence in SENTENCE_BOUNDARY.split(text):
        remaining = sentence.strip()
        while len(remaining) > max_chars:
            point = remaining.rfind(" ", 0, max_chars + 1)
            if point < max_chars // 2:
                point = max_chars
            result.append(remaining[:point].strip())
            remaining = remaining[point:].strip()
        if remaining:
            result.append(remaining)
    return result


def pop_committed(buffer: str, max_chars: int) -> tuple[list[str], str]:
    committed: list[str] = []
    while True:
        boundary = -1
        for match in re.finditer(r"[.!?。！？](?:\s|$)", buffer):
            boundary = match.end()
            break
        if boundary > 0:
            committed.extend(split_text(buffer[:boundary], max_chars))
            buffer = buffer[boundary:].lstrip()
            continue
        if len(buffer) > max_chars:
            point = buffer.rfind(" ", 0, max_chars + 1)
            if point < max_chars // 2:
                point = max_chars
            committed.append(buffer[:point].strip())
            buffer = buffer[point:].lstrip()
            continue
        break
    return [item for item in committed if item], buffer
