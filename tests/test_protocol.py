import pytest

from app.protocol import PayloadKind, ProtocolError, SequenceTracker, decode_frame, encode_frame


def test_binary_frame_round_trip():
    encoded = encode_frame(PayloadKind.MIC_PCM16, b"audio", sequence=7, timestamp_ms=42)
    frame = decode_frame(encoded, max_payload_bytes=100)
    assert frame.kind == PayloadKind.MIC_PCM16
    assert frame.sequence == 7
    assert frame.timestamp_ms == 42
    assert frame.payload == b"audio"


def test_invalid_header_and_payload_limit():
    with pytest.raises(ProtocolError, match="shorter"):
        decode_frame(b"tiny", max_payload_bytes=10)
    encoded = encode_frame(PayloadKind.SCREEN_JPEG, b"x" * 11, sequence=1, timestamp_ms=0)
    with pytest.raises(ProtocolError, match="limit"):
        decode_frame(encoded, max_payload_bytes=10)


def test_sequences_increase_per_payload_kind():
    tracker = SequenceTracker()
    mic = decode_frame(
        encode_frame(PayloadKind.MIC_PCM16, b"", sequence=2, timestamp_ms=0),
        max_payload_bytes=10,
    )
    screen = decode_frame(
        encode_frame(PayloadKind.SCREEN_JPEG, b"", sequence=1, timestamp_ms=0),
        max_payload_bytes=10,
    )
    tracker.accept(mic)
    tracker.accept(screen)
    with pytest.raises(ProtocolError, match="increase"):
        tracker.accept(mic)
