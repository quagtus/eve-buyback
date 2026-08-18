"""A logo row whose file is gone must not take the site down.

Production hit exactly this: the database pointed at a logo, the file was not on
disk (media is not persisted across image rebuilds), and every page 500'd with

    FileNotFoundError: /app/static/uploads/<name>.png

The cause was width_field/height_field on the ImageField. Django attaches a
post_init receiver that opens the image to populate them whenever they are empty
— so merely LOADING the row touched the filesystem, on every request.
"""

import pytest

from siteconfig.models import SiteConfig


@pytest.fixture
def logo_row_without_a_file(db, tmp_path, settings):
    """A row pointing at a file that does not exist, written without a save()."""
    settings.MEDIA_ROOT = tmp_path
    SiteConfig.load()
    SiteConfig.objects.filter(pk=1).update(
        site_logo="logos/vanished.png", logo_width=None, logo_height=None
    )


@pytest.mark.django_db
def test_loading_the_config_does_not_touch_the_filesystem(logo_row_without_a_file):
    config = SiteConfig.load()

    assert config.site_logo.name == "logos/vanished.png"


def test_the_image_field_has_no_dimension_fields_wired():
    """The precise cause. width_field/height_field look harmless — they cache the
    size in columns — but Django implements them with a post_init receiver that
    opens the image whenever those columns are empty. Dimensions are set in
    save() instead, from the already-decoded image."""
    field = SiteConfig._meta.get_field("site_logo")

    assert field.width_field is None, (
        "width_field makes loading the row open the image file"
    )
    assert field.height_field is None


@pytest.mark.django_db
def test_loading_the_row_never_opens_storage(logo_row_without_a_file, monkeypatch):
    """Behavioural counterpart: no read of any kind while instantiating."""
    storage = SiteConfig._meta.get_field("site_logo").storage
    opened = []
    monkeypatch.setattr(
        storage, "open", lambda name, mode="rb": opened.append(name)
    )

    SiteConfig.objects.get(pk=1)

    assert opened == [], f"storage was read during instantiation: {opened}"


@pytest.mark.django_db
def test_a_page_renders_with_a_missing_logo_file(client, logo_row_without_a_file):
    """A broken image is a cosmetic problem. A 500 is not."""
    response = client.get("/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_the_admin_still_loads_with_a_missing_logo_file(
    client, django_user_model, logo_row_without_a_file
):
    django_user_model.objects.create_superuser("a", "a@example.com", "pw12345678")
    client.login(username="a", password="pw12345678")

    assert client.get("/admin/siteconfig/siteconfig/1/change/").status_code == 200
