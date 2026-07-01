from app.vad import FRAME_BYTES, BargeInDetector


class FakeVad:
    def is_speech(self, frame, _rate):
        return any(frame)


def test_barge_in_requires_sustained_voice_and_rearms_after_silence():
    detector = BargeInDetector()
    detector.vad = FakeVad()
    voice = b"\x01\x00" * (FRAME_BYTES // 2)
    silence = b"\x00" * FRAME_BYTES
    assert not detector.feed(voice * 11, armed=True)
    assert detector.feed(voice, armed=True)
    assert not detector.feed(voice * 12, armed=True)
    detector.feed(silence * 25, armed=True)
    assert detector.feed(voice * 12, armed=True)


def test_barge_in_discards_unarmed_voice_history():
    detector = BargeInDetector()
    detector.vad = FakeVad()
    voice = b"\x01\x00" * (FRAME_BYTES // 2)
    assert not detector.feed(voice * 30, armed=False)
    assert not detector.feed(voice, armed=True)
