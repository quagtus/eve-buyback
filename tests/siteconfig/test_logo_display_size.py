"""Operator-controlled logo size in the header.

Named logo_display_* to keep them apart from logo_width/logo_height, which are
the intrinsic pixel dimensions of the stored file and are not editable.
"""

import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from siteconfig.models import SiteConfig


def a_logo():
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 300), (10, 120, 200)).save(buffer, format="PNG")
    return SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")


@pytest.fixture
def configured(db, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    config = SiteConfig.load()
    config.site_logo = a_logo()
    config.save()
    return config


@pytest.mark.django_db
def test_the_defaults_match_the_previous_hardcoded_size(db):
    """Nobody's header changes just because the setting arrived."""
    config = SiteConfig.load()

    assert config.logo_display_height == 40
    assert config.logo_display_max_width == 160


@pytest.mark.django_db
def test_the_configured_size_reaches_the_page(client, configured):
    configured.logo_display_height = 72
    configured.logo_display_max_width = 300
    configured.save()

    body = client.get("/").content.decode()

    assert "height:72px" in body.replace(" ", "")
    assert "max-width:300px" in body.replace(" ", "")


@pytest.mark.django_db
def test_the_size_is_an_inline_style_not_a_tailwind_class(client, configured):
    """Tailwind compiles its classes at build time from the templates, so a class
    built from a database value would simply not exist in the stylesheet."""
    body = client.get("/").content.decode()

    assert "h-10" not in body
    assert "max-w-[10rem]" not in body


@pytest.mark.django_db
def test_an_absurd_height_is_rejected(db):
    config = SiteConfig.load()
    config.logo_display_height = 5000

    with pytest.raises(ValidationError):
        config.full_clean()


@pytest.mark.django_db
def test_a_zero_height_is_rejected(db):
    config = SiteConfig.load()
    config.logo_display_height = 0

    with pytest.raises(ValidationError):
        config.full_clean()


@pytest.mark.django_db
def test_both_fields_are_editable_in_the_admin(client, django_user_model, db):
    django_user_model.objects.create_superuser("a", "a@example.com", "pw12345678")
    client.login(username="a", password="pw12345678")
    SiteConfig.load()

    body = client.get("/admin/siteconfig/siteconfig/1/change/").content.decode()

    assert 'name="logo_display_height"' in body
    assert 'name="logo_display_max_width"' in body


@pytest.mark.django_db
def test_the_intrinsic_dimensions_stay_out_of_the_form(client, django_user_model, db):
    """logo_width/logo_height describe the file, not a preference — editing them
    by hand would just make them disagree with the image."""
    django_user_model.objects.create_superuser("b", "b@example.com", "pw12345678")
    client.login(username="b", password="pw12345678")
    SiteConfig.load()

    body = client.get("/admin/siteconfig/siteconfig/1/change/").content.decode()

    assert 'name="logo_width"' not in body
    assert 'name="logo_height"' not in body
