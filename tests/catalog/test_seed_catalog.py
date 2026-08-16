import io
import json
import tarfile

import pytest

from catalog.management.commands.seed_catalog import import_reference_data
from catalog.models import EveCategory, EveGroup, EveType


def _lang(name):
    return {"en": name, "de": "ignored"}


def build_fixture_archive(path):
    categories = {
        "6": {"category_id": 6, "name": _lang("Ship"), "published": True},
        "4": {"category_id": 4, "name": _lang("Material"), "published": False},
    }
    groups = {
        "27": {"group_id": 27, "category_id": 6, "name": _lang("Battleship"), "published": True},
        "18": {"group_id": 18, "category_id": 4, "name": _lang("Mineral"), "published": False},
    }
    types = {
        "638": {"type_id": 638, "group_id": 27, "name": _lang("Raven"), "published": True},
        "34": {"type_id": 34, "group_id": 18, "name": _lang("Tritanium"), "published": True},
        "99": {"type_id": 99, "group_id": 27, "name": _lang("Unpublished"), "published": False},
    }
    with tarfile.open(path, "w:xz") as tar:
        for filename, payload in [
            ("categories.json", categories),
            ("groups.json", groups),
            ("types.json", types),
        ]:
            raw = json.dumps(payload).encode()
            info = tarfile.TarInfo(filename)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))


@pytest.mark.django_db
def test_import_loads_all_categories_and_groups_but_only_published_types(tmp_path):
    archive = tmp_path / "ref.tar.xz"
    build_fixture_archive(archive)

    result = import_reference_data(archive)

    # All categories and groups import, published or not, so FKs never dangle.
    assert EveCategory.objects.count() == 2
    assert EveGroup.objects.count() == 2

    # Only published types.
    assert EveType.objects.count() == 2
    assert not EveType.objects.filter(id=99).exists()

    # A published type under an unpublished group still imports cleanly.
    assert EveType.objects.get(id=34).group.category.name == "Material"

    assert EveType.objects.get(id=638).name == "Raven"
    assert result == {"categories": 2, "groups": 2, "types": 2}


@pytest.mark.django_db
def test_import_is_idempotent(tmp_path):
    archive = tmp_path / "ref.tar.xz"
    build_fixture_archive(archive)

    import_reference_data(archive)
    import_reference_data(archive)

    assert EveCategory.objects.count() == 2
    assert EveType.objects.count() == 2
