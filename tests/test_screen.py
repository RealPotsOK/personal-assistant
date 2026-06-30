import io

import pytest
from PIL import Image

from app.screen import ScreenError, ScreenFrame, normalize_screen


def image_bytes(format_name="JPEG", size=(2000, 1000)):
    output = io.BytesIO()
    Image.new("RGB", size, "green").save(output, format=format_name)
    return output.getvalue()


def test_screen_decoding_downsampling_and_data_url():
    normalized = normalize_screen(
        image_bytes(), "image/jpeg", max_bytes=1_000_000, max_pixels=200_000
    )
    with Image.open(io.BytesIO(normalized)) as image:
        assert image.width * image.height <= 200_000
    frame = ScreenFrame(1, 0, "image/jpeg", normalized)
    assert frame.data_url().startswith("data:image/jpeg;base64,")


def test_screen_rejects_bad_data_and_size():
    with pytest.raises(ScreenError, match="decoded"):
        normalize_screen(b"not an image", "image/jpeg", max_bytes=100, max_pixels=100)
    with pytest.raises(ScreenError, match="byte limit"):
        normalize_screen(image_bytes(), "image/jpeg", max_bytes=10, max_pixels=100)
