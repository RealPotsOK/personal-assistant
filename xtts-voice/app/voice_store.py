from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from safetensors.torch import load_file, save_file

from app.errors import APIError


class VoiceStore:
    def __init__(self, root: str, model_id: str) -> None:
        self.root = Path(root)
        self.model_id = model_id
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, voice_id: str) -> Path:
        if not voice_id.startswith("voice_") or not all(char.isalnum() or char in "_-" for char in voice_id):
            raise APIError("Invalid voice_id", 400, "invalid_voice_id")
        return self.root / voice_id

    def save(self, conditioning, embedding, *, name: str | None, reference_seconds: float) -> dict:
        voice_id = f"voice_{uuid.uuid4().hex[:16]}"
        target = self._path(voice_id)
        target.mkdir(mode=0o700)
        metadata = {
            "voice_id": voice_id,
            "name": name.strip()[:80] if name and name.strip() else None,
            "model": self.model_id,
            "created_at": datetime.now(UTC).isoformat(),
            "reference_seconds": round(reference_seconds, 3),
        }
        save_file(
            {
                "gpt_cond_latent": conditioning.detach().cpu().contiguous(),
                "speaker_embedding": embedding.detach().cpu().contiguous(),
            },
            target / "conditioning.safetensors",
        )
        temporary = target / "metadata.json.tmp"
        temporary.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        os.replace(temporary, target / "metadata.json")
        return metadata

    def list(self) -> list[dict]:
        records: list[dict] = []
        for metadata in self.root.glob("voice_*/metadata.json"):
            try:
                records.append(json.loads(metadata.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def get(self, voice_id: str):
        target = self._path(voice_id)
        tensor_path = target / "conditioning.safetensors"
        if not tensor_path.is_file():
            raise APIError("Voice not found", 404, "voice_not_found")
        tensors = load_file(tensor_path, device="cpu")
        return tensors["gpt_cond_latent"], tensors["speaker_embedding"]

    def delete(self, voice_id: str) -> None:
        target = self._path(voice_id)
        if not target.is_dir():
            raise APIError("Voice not found", 404, "voice_not_found")
        shutil.rmtree(target)
