"""Uploading, replacing and clearing the site logo.

ImageField never deletes anything on its own, so without this every replacement
would leave the previous file on disk forever — invisible, and growing.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.test.utils import override_settings
from PIL import Image

from siteconfig.models import SiteConfig


def upload(name="logo.png", size=(1200, 400), mode="RGB"):
    buffer = io.BytesIO()
    Image.new(mode, size, (10, 120, 200)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.mark.django_db
def test_an_uploaded_logo_is_shrunk_on_save(media):
    config = SiteConfig.load()
    config.site_logo = upload(size=(3000, 3000))
    config.save()

    with config.site_logo.open("rb") as handle:
        assert max(Image.open(handle).size) == 512


@pytest.mark.django_db
def test_replacing_the_logo_removes_the_previous_file(media):
    config = SiteConfig.load()
    config.site_logo = upload(name="first.png")
    config.save()
    first = config.site_logo.name
    assert default_storage.exists(first)

    config.site_logo = upload(name="second.png")
    config.save()

    assert config.site_logo.name != first
    assert not default_storage.exists(first), "the replaced logo was left on disk"
    assert default_storage.exists(config.site_logo.name)


@pytest.mark.django_db
def test_clearing_the_logo_removes_the_file(media):
    config = SiteConfig.load()
    config.site_logo = upload()
    config.save()
    stored = config.site_logo.name

    config.site_logo = None
    config.save()

    assert not default_storage.exists(stored)
    assert not SiteConfig.load().site_logo


@pytest.mark.django_db
def test_saving_other_settings_does_not_touch_the_logo(media):
    """Reprocessing on every save would re-encode the JPEG each time, losing a
    little quality on every unrelated edit."""
    config = SiteConfig.load()
    config.site_logo = upload(name="stable.png")
    config.save()
    stored = config.site_logo.name
    with config.site_logo.open("rb") as handle:
        before = handle.read()

    config.site_name = "Changed"
    config.save()

    reloaded = SiteConfig.load()
    assert reloaded.site_logo.name == stored
    with reloaded.site_logo.open("rb") as handle:
        assert handle.read() == before


@pytest.mark.django_db
def test_an_oversized_upload_is_rejected_without_saving(media):
    from siteconfig.images import LOGO_MAX_UPLOAD_BYTES, LogoTooLargeError

    config = SiteConfig.load()
    config.site_logo = SimpleUploadedFile(
        "huge.jpg", b"\xff\xd8\xff" + b"0" * LOGO_MAX_UPLOAD_BYTES,
        content_type="image/jpeg",
    )

    with pytest.raises(LogoTooLargeError):
        config.save()

    assert not SiteConfig.load().site_logo


@pytest.mark.django_db
def test_new_logos_land_in_their_own_directory(media):
    config = SiteConfig.load()
    config.site_logo = upload()
    config.save()

    assert config.site_logo.name.startswith("logos/")
