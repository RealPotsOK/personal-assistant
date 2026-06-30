from app.text import SentenceChunker, needs_screen


def test_visual_intent_and_explicit_hint():
    assert needs_screen("What is this on my screen?")
    assert needs_screen("Explain the report", explicit=True)
    assert not needs_screen("What is the weather tomorrow?")


def test_sentence_chunking_across_deltas():
    chunker = SentenceChunker(240)
    assert chunker.feed("Hello there. Next") == ["Hello there."]
    assert chunker.feed(" sentence!") == []
    assert chunker.flush() == ["Next sentence!"]


def test_abbreviation_is_not_split_and_long_text_is_bounded():
    chunker = SentenceChunker(40)
    assert chunker.feed("Ask Dr. Smith for the result. Thank you. ") == [
        "Ask Dr. Smith for the result.",
        "Thank you.",
    ]
    long = SentenceChunker(32)
    pieces = long.feed("word " * 20) + long.flush()
    assert all(len(piece) <= 32 for piece in pieces)
