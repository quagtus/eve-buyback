"""Importing reprocessing yields from a synthetic EVERef archive.

Built in-process rather than downloaded: the real archive is 14 MB compressed and
239 MB of types.json, and the behaviour worth testing is which rows survive.
"""

import io
import json
import tarfile
from pathlib import Path

import pytest

from catalog.management.commands.seed_catalog import import_reference_data
from catalog.models import EveType, EveTypeMaterial


def build_archive(tmp_path: Path, types: dict) -> Path:
    categories = {
        "25": {"name": {"en": "Asteroid"}},
        "4": {"name": {"en": "Material"}},
    }
    groups = {
        "462": {"name": {"en": "Veldspar"}, "category_id": 25},
        "18": {"name": {"en": "Mineral"}, "category_id": 4},
    }
    archive = tmp_path / "reference-data.tar.xz"
    with tarfile.open(archive, "w:xz") as tar:
        for name, payload in (
            ("categories.json", categories),
            ("groups.json", groups),
            ("types.json", types),
        ):
            blob = json.dumps(payload).encode()
            info = tarfile.TarInfo(name)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
    return archive


def ore_and_mineral(**ore_extra):
    ore = {
        "name": {"en": "Veldspar"},
        "group_id": 462,
        "published": True,
        "portion_size": 100,
        "type_materials": {"34": {"material_type_id": 34, "quantity": 400}},
    }
    ore.update(ore_extra)
    return {
        "1230": ore,
        "34": {"name": {"en": "Tritanium"}, "group_id": 18, "published": True},
    }


@pytest.mark.django_db
def test_portion_size_is_imported(tmp_path):
    import_reference_data(build_archive(tmp_path, ore_and_mineral()))

    assert EveType.objects.get(id=1230).portion_size == 100


@pytest.mark.django_db
def test_a_type_without_portion_size_defaults_to_one(tmp_path):
    types = ore_and_mineral()
    del types["1230"]["portion_size"]

    import_reference_data(build_archive(tmp_path, types))

    assert EveType.objects.get(id=1230).portion_size == 1


@pytest.mark.django_db
def test_materials_are_imported(tmp_path):
    counts = import_reference_data(build_archive(tmp_path, ore_and_mineral()))

    row = EveTypeMaterial.objects.get()
    assert (row.type_id, row.material_id, row.quantity) == (1230, 34, 400)
    assert counts["materials"] == 1


@pytest.mark.django_db
def test_a_material_referencing_an_unimported_type_is_skipped_not_raised(tmp_path):
    """9 541 types carry reprocessing data but only 26 992 types are published,
    so dangling references exist in the real archive. The original seeder hit
    exactly this class of foreign-key break when filtering on `published`."""
    types = ore_and_mineral()
    types["1230"]["type_materials"]["99999"] = {
        "material_type_id": 99999,
        "quantity": 7,
    }

    counts = import_reference_data(build_archive(tmp_path, types))

    assert EveTypeMaterial.objects.count() == 1
    assert counts["materials"] == 1
    assert counts["materials_skipped"] == 1


@pytest.mark.django_db
def test_an_unpublished_type_contributes_no_materials(tmp_path):
    types = ore_and_mineral(published=False)

    import_reference_data(build_archive(tmp_path, types))

    assert EveTypeMaterial.objects.count() == 0


@pytest.mark.django_db
def test_reseeding_replaces_yields_rather_than_duplicating(tmp_path):
    """CCP changes yields; a second run must not violate the unique constraint."""
    archive = build_archive(tmp_path, ore_and_mineral())
    import_reference_data(archive)

    changed = ore_and_mineral()
    changed["1230"]["type_materials"]["34"]["quantity"] = 415
    import_reference_data(build_archive(tmp_path, changed))

    row = EveTypeMaterial.objects.get()
    assert row.quantity == 415
