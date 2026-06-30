import base64
import io
from dataclasses import replace

import pytest
from PIL import Image

from app.config import settings
from app.core.images import ImageError, ImageLoader


class UnusedFetcher:
    async def fetch(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("network fetch should not be used")


def make_data_url(width: int = 20, height: int = 10) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


@pytest.mark.asyncio
async def test_loads_and_resizes_data_url() -> None:
    config = replace(settings, max_image_pixels=50)
    loader = ImageLoader(config, UnusedFetcher())
    image = await loader.load(make_data_url())
    assert image.mode == "RGB"
    assert image.width * image.height <= 50


@pytest.mark.asyncio
async def test_rejects_invalid_data_url() -> None:
    loader = ImageLoader(settings, UnusedFetcher())
    with pytest.raises(ImageError):
        await loader.load("data:image/png;base64,not-valid-!!!")
