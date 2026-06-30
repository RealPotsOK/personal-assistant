from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

MAGIC = b"PA01"
HEADER = struct.Struct(">4sBBHII")
HEADER_SIZE = HEADER.size


class PayloadKind(IntEnum):
    MIC_PCM16 = 0x01
    SCREEN_JPEG = 0x02
    SCREEN_PNG = 0x03
    TTS_PCM16 = 0x81


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BinaryFrame:
    kind: PayloadKind
    flags: int
    sequence: int
    timestamp_ms: int
    payload: bytes


def encode_frame(
    kind: PayloadKind,
    payload: bytes,
    *,
    sequence: int,
    timestamp_ms: int,
    flags: int = 0,
) -> bytes:
    if not 0 <= flags <= 255:
        raise ProtocolError("flags must fit in one byte")
    if not 0 <= sequence <= 0xFFFFFFFF or not 0 <= timestamp_ms <= 0xFFFFFFFF:
        raise ProtocolError("sequence and timestamp must fit in uint32")
    return HEADER.pack(MAGIC, int(kind), flags, 0, sequence, timestamp_ms) + payload


def decode_frame(data: bytes, *, max_payload_bytes: int) -> BinaryFrame:
    if len(data) < HEADER_SIZE:
        raise ProtocolError("binary frame is shorter than the 16-byte header")
    magic, kind_value, flags, reserved, sequence, timestamp_ms = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ProtocolError("invalid binary frame magic")
    if reserved:
        raise ProtocolError("reserved header bytes must be zero")
    try:
        kind = PayloadKind(kind_value)
    except ValueError as error:
        raise ProtocolError(f"unsupported binary payload kind {kind_value}") from error
    payload = data[HEADER_SIZE:]
    if len(payload) > max_payload_bytes:
        raise ProtocolError("binary payload exceeds the configured limit")
    return BinaryFrame(kind, flags, sequence, timestamp_ms, payload)


class SequenceTracker:
    def __init__(self) -> None:
        self._last: dict[PayloadKind, int] = {}

    def accept(self, frame: BinaryFrame) -> None:
        previous = self._last.get(frame.kind)
        if previous is not None and frame.sequence <= previous:
            raise ProtocolError("binary sequence must increase for each payload kind")
        self._last[frame.kind] = frame.sequence
