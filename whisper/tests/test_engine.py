from __future__ import annotations

import pytest

from app.config import Settings
from app.core.engine import InferenceEngine
from app.errors import APIError, CapacityError, QueueFullError


def settings(tmp_path, **overrides) -> Settings:
    return Settings(
        api_key="test-shared-key-that-is-long-enough",
        model_path=str(tmp_path),
        **overrides,
    )


async def test_missing_model_is_recoverable(tmp_path):
    engine = InferenceEngine(settings(tmp_path))
    with pytest.raises(APIError) as caught:
        await engine.ensure_loaded()
    assert caught.value.status_code == 503
    assert caught.value.code == "model_unavailable"
    assert engine.model is None


async def test_cuda_oom_becomes_capacity_error(tmp_path, monkeypatch):
    engine = InferenceEngine(settings(tmp_path))

    def fail():
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(engine, "_load_sync", fail)
    with pytest.raises(CapacityError) as caught:
        await engine.ensure_loaded()
    assert caught.value.code == "gpu_capacity_unavailable"


async def test_queue_overflow_is_rejected(tmp_path):
    engine = InferenceEngine(settings(tmp_path, max_queue=0))
    await engine._inference_lock.acquire()
    try:
        with pytest.raises(QueueFullError) as caught:
            async with engine.slot():
                pass
        assert caught.value.status_code == 429
    finally:
        engine._inference_lock.release()
