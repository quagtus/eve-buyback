"""The site logo is processed on upload and cleaned up on replacement.

Two real failures motivate this. A 2.4 MB wallpaper was accepted as a "logo" and
then served to every visitor on every page load. And because ImageField never
removes anything, each replacement left the previous file on disk forever.
"""

import io
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from siteconfig.images import (
    LOGO_MAX_EDGE,
    LOGO_MAX_UPLOAD_BYTES,
    LogoTooLargeError,
    process_logo,
)


def make_image(width, height, mode="RGB", fmt="PNG", colour=(200, 60, 20)):
    buffer = io.BytesIO()
    Image.new(mode, (width, height), colour if mode != "RGBA" else (*colour, 255)).save(
        buffer, format=fmt
    )
    return buffer.getvalue()


def upload(data, name="logo.png", content_type="image/png"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def opened(processed):
    processed.seek(0)
    return Image.open(io.BytesIO(processed.read()))


def test_an_oversized_image_is_scaled_down():
    """A wallpaper must not be served as a header logo."""
    processed = process_logo(upload(make_image(3840, 2160)))

    image = opened(processed)
    assert max(image.size) == LOGO_MAX_EDGE


def test_the_aspect_ratio_is_preserved():
    """Cropping a wide logo to a square would cut its sides off."""
    processed = process_logo(upload(make_image(2000, 500)))

    width, height = opened(processed).size
    assert width / height == pytest.approx(4.0, rel=0.02)


def test_a_small_image_is_not_upscaled():
    processed = process_logo(upload(make_image(64, 64)))

    assert opened(processed).size == (64, 64)


def test_processing_shrinks_the_payload_dramatically():
    """The whole point: what reaches visitors is small."""
    original = make_image(3840, 2160, fmt="JPEG")
    processed = process_logo(upload(original, name="logo.jpg", content_type="image/jpeg"))

    processed.seek(0)
    assert len(processed.read()) < len(original) / 10


def test_transparency_is_kept():
    """Logos are usually PNGs with an alpha channel; flattening adds a box."""
    processed = process_logo(upload(make_image(600, 600, mode="RGBA")))

    assert opened(processed).mode in ("RGBA", "LA", "P")


def test_an_opaque_image_does_not_become_a_bloated_png():
    """A photo saved as PNG at 512px is far larger than the same as JPEG."""
    processed = process_logo(
        upload(make_image(2000, 2000, fmt="JPEG"), name="p.jpg", content_type="image/jpeg")
    )

    processed.seek(0)
    assert len(processed.read()) < 200_000


def test_a_file_over_the_upload_limit_is_refused():
    """Refused before decoding: a decompression bomb must not be opened first."""
    too_big = b"\xff\xd8\xff" + b"0" * (LOGO_MAX_UPLOAD_BYTES + 1)

    with pytest.raises(LogoTooLargeError) as exc:
        process_logo(upload(too_big, name="huge.jpg", content_type="image/jpeg"))

    assert "MB" in str(exc.value)


def test_something_that_is_not_an_image_is_refused():
    with pytest.raises(ValidationError):
        process_logo(upload(b"this is not an image", name="x.png"))


def test_the_processed_name_keeps_a_sensible_extension():
    processed = process_logo(upload(make_image(800, 800)))

    assert Path(processed.name).suffix in (".png", ".jpg")
