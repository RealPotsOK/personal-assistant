from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError


class ScreenError(ValueError):
    pass


@dataclass(slots=True)
class ScreenFrame:
    sequence: int
    captured_monotonic: float
    mime_type: str
    data: bytes
    explicit: bool = False
    application: str | None = None
    window_title: str | None = None

    def fresh(self, seconds: int) -> bool:
        return time.monotonic() - self.captured_monotonic <= seconds

    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{base64.b64encode(self.data).decode('ascii')}"


def normalize_screen(data: bytes, mime_type: str, *, max_bytes: int, max_pixels: int) -> bytes:
    if len(data) > max_bytes:
        raise ScreenError("screen frame exceeds the configured byte limit")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG"}:
                raise ScreenError("screen frame must be JPEG or PNG")
            expected = "PNG" if mime_type == "image/png" else "JPEG"
            if source.format != expected:
                raise ScreenError("screen frame kind does not match its encoded format")
            if source.width * source.height > max_pixels * 16:
                raise ScreenError("screen frame dimensions exceed the safe decode limit")
            source.load()
            image = source.convert("RGB")
    except ScreenError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ScreenError("screen frame could not be decoded") from error
    pixels = image.width * image.height
    if pixels > max_pixels:
        scale = (max_pixels / pixels) ** 0.5
        image.thumbnail((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    output = io.BytesIO()
    if mime_type == "image/png":
        image.save(output, format="PNG", optimize=True)
    else:
        image.save(output, format="JPEG", quality=85, optimize=True)
    value = output.getvalue()
    if len(value) > max_bytes:
        raise ScreenError("normalized screen frame exceeds the configured byte limit")
    return value
