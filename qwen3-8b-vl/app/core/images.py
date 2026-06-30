from __future__ import annotations

import base64
import binascii
import io
import math
import re

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.core.safe_http import FetchError, SafeFetcher


class ImageError(Exception):
    pass


_DATA_URL_RE = re.compile(
    r"^data:(image/(?:jpeg|png|webp|gif));base64,([a-zA-Z0-9+/=\r\n]+)$",
    re.IGNORECASE,
)
_REMOTE_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


class ImageLoader:
    def __init__(self, settings: Settings, fetcher: SafeFetcher) -> None:
        self.settings = settings
        self.fetcher = fetcher

    async def load(self, url: str) -> Image.Image:
        if url.lower().startswith("data:"):
            content = self._decode_data_url(url)
        else:
            try:
                result = await self.fetcher.fetch(
                    url,
                    max_bytes=self.settings.max_image_bytes,
                    allowed_content_types=_REMOTE_IMAGE_TYPES,
                )
            except FetchError as exc:
                raise ImageError(str(exc)) from exc
            content = result.content
        return self._decode_image(content)

    def _decode_data_url(self, value: str) -> bytes:
        match = _DATA_URL_RE.fullmatch(value)
        if not match:
            raise ImageError("image data URL must contain a supported base64-encoded image")
        encoded = "".join(match.group(2).split())
        if len(encoded) > ((self.settings.max_image_bytes + 2) // 3) * 4 + 4:
            raise ImageError("image exceeds the size limit")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageError("image data URL contains invalid base64") from exc
        if len(content) > self.settings.max_image_bytes:
            raise ImageError("image exceeds the size limit")
        return content

    def _decode_image(self, content: bytes) -> Image.Image:
        try:
            source = Image.open(io.BytesIO(content))
            if source.format not in _FORMATS:
                raise ImageError(f"unsupported image format: {source.format or 'unknown'}")
            if source.format == "GIF":
                source.seek(0)
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
        except ImageError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageError("image could not be decoded") from exc

        pixels = image.width * image.height
        if pixels > self.settings.max_image_pixels:
            scale = math.sqrt(self.settings.max_image_pixels / pixels)
            size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
            image.thumbnail(size, Image.Resampling.LANCZOS)
        return image
