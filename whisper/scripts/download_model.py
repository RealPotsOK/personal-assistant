#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
import time
import urllib.request
from pathlib import Path

MODELS = {
    "small.en": {
        "repo": "faster-whisper-small.en",
        "commit": "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
        "files": {
            "config.json": (2657, "666a9605530ac1f61fa8177f3702b4dacec9966749e42610839fcc32661d5fae"),
            "model.bin": (483545366, "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a"),
            "tokenizer.json": (2128466, "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df"),
            "vocabulary.txt": (422309, "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf"),
        },
    },
    "small": {
        "repo": "faster-whisper-small",
        "commit": "536b0662742c02347bc0e980a01041f333bce120",
        "files": {
            "config.json": (2370, "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"),
            "model.bin": (483546902, "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"),
            "tokenizer.json": (2203239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
            "vocabulary.txt": (459861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
        },
    },
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def download(url: str, target: Path, size: int, sha256: str) -> None:
    if target.is_file() and target.stat().st_size == size and digest(target) == sha256:
        print(f"verified {target.name}")
        return
    temporary = target.with_suffix(target.suffix + ".part")
    print(f"downloading {target.name} ({size / 1024 / 1024:.1f} MiB)")
    for attempt in range(10):
        received = temporary.stat().st_size if temporary.exists() else 0
        if received >= size:
            break
        headers = {"User-Agent": "local-whisper-model-setup/1.0"}
        if received:
            headers["Range"] = f"bytes={received}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                if received and response.status != 206:
                    received = 0
                    temporary.unlink(missing_ok=True)
                with temporary.open("ab" if received else "wb") as output:
                    while chunk := response.read(8 * 1024 * 1024):
                        output.write(chunk)
                        received += len(chunk)
                        if received and received % (64 * 1024 * 1024) < len(chunk):
                            print(f"  {received / size:.0%}")
        except OSError as exc:
            print(f"  retry {attempt + 1}/10 after {exc}")
        if temporary.exists() and temporary.stat().st_size == size:
            break
        time.sleep(min(attempt + 1, 5))
    received = temporary.stat().st_size if temporary.exists() else 0
    if received != size:
        raise RuntimeError(f"Incomplete download for {target.name}: {received} of {size} bytes")
    if digest(temporary) != sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum or size verification failed for {target.name}")
    temporary.replace(target)


def main() -> None:
    variant = sys.argv[1] if len(sys.argv) > 1 else "small.en"
    if variant not in MODELS:
        raise SystemExit("Variant must be small.en or small")
    destination = Path(sys.argv[2] if len(sys.argv) > 2 else f"~/models/whisper/{variant}").expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    model = MODELS[variant]
    base = f"https://huggingface.co/Systran/{model['repo']}/resolve/{model['commit']}"
    for name, (size, sha256) in model["files"].items():
        download(f"{base}/{name}", destination / name, size, sha256)
    print(f"Whisper {variant} is ready at {destination}")


if __name__ == "__main__":
    main()
