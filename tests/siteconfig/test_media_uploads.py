"""Uploads must land in the ignored media directory, not the source tree.

MEDIA_ROOT was previously unset, so ImageField.upload_to resolved against the
working directory and admin uploads were written loose into the repo — which is
how a 2.4 MB wallpaper ended up committed.
"""

import pathlib

import pytest
from django.conf import settings
from django.core.files.base import ContentFile
from django.test import Client
from django.test.utils import override_settings

from siteconfig.models import SiteConfig

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


def test_media_root_is_configured():
    """An unset MEDIA_ROOT silently writes uploads relative to the CWD."""
    assert settings.MEDIA_ROOT, "MEDIA_ROOT is unset — uploads will land in the source tree"
    assert pathlib.Path(settings.MEDIA_ROOT).name == "uploads"


def test_media_url_is_not_inside_static_url():
    """Django refuses to start when it is.

    'runserver can't serve media if MEDIA_URL is within STATIC_URL' — the on-disk
    location may live under static/, but the URL must not.
    """
    static_url = settings.STATIC_URL.strip("/")
    media_url = settings.MEDIA_URL.strip("/")

    assert not media_url.startswith(f"{static_url}/"), (
        f"MEDIA_URL {settings.MEDIA_URL} is inside STATIC_URL {settings.STATIC_URL}; "
        f"Django will refuse to start"
    )


@pytest.mark.django_db
def test_uploaded_logo_is_written_inside_media_root(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        config = SiteConfig.load()
        config.site_logo.save("probe.png", ContentFile(PNG), save=True)

        stored = pathlib.Path(config.site_logo.path)
        try:
            # Inside MEDIA_ROOT, not necessarily directly in it: logos go to a
            # logos/ subdirectory. What matters is that nothing escapes into the
            # source tree, which is the bug this file exists for.
            assert stored.is_relative_to(tmp_path), (
                f"upload escaped MEDIA_ROOT: {stored}"
            )
            assert stored.exists()
        finally:
            stored.unlink(missing_ok=True)


@pytest.mark.django_db
def test_uploaded_media_is_served(tmp_path):
    """WhiteNoise only serves STATIC_ROOT, which collectstatic fills at build
    time — a logo uploaded afterwards would 404 without an explicit route."""
    with override_settings(MEDIA_ROOT=tmp_path, ALLOWED_HOSTS=["testserver"], DEBUG=False):
        config = SiteConfig.load()
        config.site_logo.save("served.png", ContentFile(PNG), save=True)
        try:
            response = Client().get(config.site_logo.url)
            assert response.status_code == 200, (
                f"{config.site_logo.url} returned {response.status_code}; "
                f"uploads are not reachable in production"
            )
        finally:
            pathlib.Path(config.site_logo.path).unlink(missing_ok=True)
