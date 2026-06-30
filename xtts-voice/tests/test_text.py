from app.core.text import pop_committed, split_text


def test_split_text_preserves_order_and_bounds():
    text = "First sentence. " + "word " * 80 + "Done!"
    segments = split_text(text, 80)
    assert segments[0] == "First sentence."
    assert all(len(segment) <= 80 for segment in segments)
    assert segments[-1].endswith("Done!")


def test_pop_committed_keeps_incomplete_tail():
    committed, remaining = pop_committed("Hello there. This is still arriving", 240)
    assert committed == ["Hello there."]
    assert remaining == "This is still arriving"
