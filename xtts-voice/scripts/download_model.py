#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

COMMIT = "6c2b0d75eae4b7047358e3b6bd9325f857d43f77"
BASE = f"https://huggingface.co/coqui/XTTS-v2/resolve/{COMMIT}"
FILES = {
    "config.json": (4368, "ef262b1454dd2a77e1461b0b2cd53e19b8a7624cc131b837d36df67356bc75e8"),
    "vocab.json": (361219, "928260878a59da8a72a2a5b7687fea29d5106137669d90945430fe17e415304a"),
    "dvae.pth": (210514388, "b29bc227d410d4991e0a8c09b858f77415013eeb9fba9650258e96095557d97a"),
    "mel_stats.pth": (1067, "1f69422a8a8f344c4fca2f0c6b8d41d2151d6615b7321e48e6bb15ae949b119c"),
    "model.pth": (1867929118, "c7ea20001c6a0a841c77e252d8409f6a74fb423e79b3206a0771ba5989776187"),
    "speakers_xtts.pth": (7754818, "f0f6137c19a4eab0cbbe4c99b5babacf68b1746e50da90807708c10e645b943b"),
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def download(name: str, target: Path, size: int, sha256: str) -> None:
    if target.is_file() and target.stat().st_size == size and digest(target) == sha256:
        print(f"verified {name}")
        return
    temporary = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(f"{BASE}/{name}", headers={"User-Agent": "xtts-voice-model-setup/1.0"})
    received = 0
    value = hashlib.sha256()
    print(f"downloading {name} ({size / 1024 / 1024:.1f} MiB)")
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
        while chunk := response.read(8 * 1024 * 1024):
            output.write(chunk)
            value.update(chunk)
            received += len(chunk)
            if received and received % (128 * 1024 * 1024) < len(chunk):
                print(f"  {received / size:.0%}")
    if received != size or value.hexdigest() != sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum or size verification failed for {name}")
    temporary.replace(target)


def main() -> None:
    if os.getenv("COQUI_TOS_AGREED") != "1":
        raise SystemExit(
            "Set COQUI_TOS_AGREED=1 only after reading and accepting the Coqui Public Model License"
        )
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "~/models/xtts-v2").expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    for name, (size, sha256) in FILES.items():
        download(name, destination / name, size, sha256)
    print(f"XTTS-v2 model is ready at {destination}")


if __name__ == "__main__":
    main()
