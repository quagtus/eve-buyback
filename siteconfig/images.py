"""Turn an uploaded file into a logo that is safe to serve on every page.

Motivated by two real failures. A 2.4 MB wallpaper was accepted as a "logo" and
then sent to every visitor on every page load. And ImageField never deletes
anything, so each replacement left the previous file on disk forever — the
deletion side lives in the model, but the shrinking happens here.
"""

import io
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

# A logo is rendered at around 40px tall. 512 leaves generous room for high-DPI
# displays without the file ever being large.
LOGO_MAX_EDGE = 512

# Checked before Pillow opens anything: a decompression bomb is small on disk and
# enormous in memory, so the cheap guard has to come first.
LOGO_MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# Opaque images become JPEG — a 512px photo is roughly ten times smaller that way
# than as PNG. Anything with transparency stays PNG, because flattening alpha
# puts a solid box behind a logo designed to sit on the page background.
JPEG_QUALITY = 85
ALPHA_MODES = frozenset({"RGBA", "LA", "PA"})


class LogoTooLargeError(ValidationError):
    """The upload exceeds LOGO_MAX_UPLOAD_BYTES."""


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in ALPHA_MODES or "transparency" in image.info


def process_logo(uploaded) -> ContentFile:
    """Validate, shrink and re-encode an uploaded logo.

    Returns a ContentFile ready to assign to the ImageField. Raises
    LogoTooLargeError or ValidationError; both are ValidationError subclasses, so
    the admin renders either as a field error rather than a 500.
    """
    size = getattr(uploaded, "size", None)
    if size is not None and size > LOGO_MAX_UPLOAD_BYTES:
        limit_mb = LOGO_MAX_UPLOAD_BYTES // (1024 * 1024)
        raise LogoTooLargeError(
            f"That file is {size / 1024 / 1024:.1f} MB. Logos are limited to "
            f"{limit_mb} MB — it is resized for display anyway, so a small "
            "image is all that is needed."
        )

    uploaded.seek(0)
    try:
        image = Image.open(uploaded)
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError(
            "That file could not be read as an image. Upload a PNG, JPEG or WebP."
        ) from exc

    # thumbnail() only ever shrinks, so a small logo is left untouched rather
    # than upscaled into a blurry one.
    image.thumbnail((LOGO_MAX_EDGE, LOGO_MAX_EDGE), Image.LANCZOS)

    buffer = io.BytesIO()
    stem = Path(getattr(uploaded, "name", "logo")).stem or "logo"
    if _has_alpha(image):
        image.convert("RGBA").save(buffer, format="PNG", optimize=True)
        name = f"{stem}.png"
    else:
        image.convert("RGB").save(
            buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True
        )
        name = f"{stem}.jpg"

    processed = ContentFile(buffer.getvalue(), name=name)
    # Carried on the returned file so the caller can store the dimensions without
    # reopening the image. ImageField's width_field/height_field would do this
    # too, but at the cost of a post_init receiver that reads the file on every
    # model instantiation.
    processed.image_size = image.size
    return processed
