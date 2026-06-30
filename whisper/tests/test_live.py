import struct

from app.core.live import FRAME_BYTES, LiveAudioBuffer, remove_word_overlap


class FakeVad:
    def is_speech(self, frame, _sample_rate):
        return any(frame)


def test_overlap_removal():
    assert remove_word_overlap("hello from the assistant", "the assistant is ready") == "is ready"
    assert remove_word_overlap("one two", "three four") == "three four"


def test_live_buffer_emits_partial_and_final():
    buffer = LiveAudioBuffer(
        partial_interval_ms=200,
        final_silence_ms=200,
        max_utterance_ms=5_000,
        overlap_ms=200,
    )
    buffer.vad = FakeVad()
    voiced = struct.pack("<h", 10_000) * (FRAME_BYTES // 2)
    silence = b"\x00" * FRAME_BYTES
    jobs = []
    for _ in range(20):
        jobs.extend(buffer.feed(voiced))
    for _ in range(12):
        jobs.extend(buffer.feed(silence))
    assert any(job.kind == "partial" for job in jobs)
    assert jobs[-1].kind == "final"


def test_commit_flushes_current_audio():
    buffer = LiveAudioBuffer(
        partial_interval_ms=800,
        final_silence_ms=700,
        max_utterance_ms=5_000,
        overlap_ms=0,
    )
    buffer.utterance.extend(b"\x00\x01" * 320)
    buffer.in_speech = True
    job = buffer.commit()
    assert job is not None
    assert job.kind == "final"
    assert buffer.commit() is None
