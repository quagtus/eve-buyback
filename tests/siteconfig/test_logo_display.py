"""How the logo is rendered in the site header.

The header previously forced every logo into a 40x40 square with object-cover,
which crops the sides off anything that is not square — and most logos are wide.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from siteconfig.models import SiteConfig

TEMPLATE = "templates/base.html"


def wide_logo():
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 300), (10, 120, 200)).save(buffer, format="PNG")
    return SimpleUploadedFile("wide.png", buffer.getvalue(), content_type="image/png")


@pytest.fixture
def configured(db, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    config = SiteConfig.load()
    config.site_name = "Test Buyback"
    config.site_logo = wide_logo()
    config.save()
    return config


def test_the_header_does_not_crop_the_logo():
    markup = open(TEMPLATE).read()

    assert "object-cover" not in markup, (
        "object-cover crops a wide logo to a square, cutting its sides off"
    )
    assert "object-contain" in markup


@pytest.mark.django_db
def test_the_logo_is_rendered_with_its_stored_dimensions(client, configured):
    """width and height attributes reserve the space before the image loads, so
    the header does not jump as it arrives."""
    body = client.get("/").content.decode()

    assert f'width="{configured.logo_width}"' in body
    assert f'height="{configured.logo_height}"' in body


@pytest.mark.django_db
def test_the_stored_dimensions_are_the_processed_ones(configured):
    """Not the 1200x300 that was uploaded: it is resized to fit 512."""
    assert configured.logo_width == 512
    assert configured.logo_height == 128


@pytest.mark.django_db
def test_a_site_without_a_logo_renders_no_image(client, db):
    config = SiteConfig.load()
    config.site_name = "No Logo"
    config.save()

    body = client.get("/").content.decode()

    assert "<img" not in body or "logo" not in body.split("<header")[1].split("</header")[0]
