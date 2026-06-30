import torch

from app.voice_store import VoiceStore


def test_voice_store_round_trip_and_delete(tmp_path):
    store = VoiceStore(str(tmp_path), "xtts-v2")
    metadata = store.save(
        torch.ones((1, 4, 8)),
        torch.zeros((1, 512, 1)),
        name="Test voice",
        reference_seconds=4.25,
    )
    assert metadata["voice_id"].startswith("voice_")
    assert store.list()[0]["name"] == "Test voice"
    conditioning, embedding = store.get(metadata["voice_id"])
    assert conditioning.shape == (1, 4, 8)
    assert embedding.shape == (1, 512, 1)
    assert not list(tmp_path.rglob("*.wav"))
    store.delete(metadata["voice_id"])
    assert store.list() == []
