"""Reprocessing yields, as EVERef publishes them.

The quantity is what ONE batch of portion_size yields — not one unit. Veldspar
has portion_size 100 and quantity 400, meaning 100 units give 400 Tritanium.
Reading it as per-unit overstates ore value by 100x.
"""

import pytest

from catalog.models import EveCategory, EveGroup, EveType, EveTypeMaterial


@pytest.fixture
def veldspar(db):
    asteroid = EveCategory.objects.create(id=25, name="Asteroid")
    material = EveCategory.objects.create(id=4, name="Material")
    ore_group = EveGroup.objects.create(id=462, name="Veldspar", category=asteroid)
    mineral = EveGroup.objects.create(id=18, name="Mineral", category=material)

    ore = EveType.objects.create(
        id=1230, name="Veldspar", group=ore_group, portion_size=100
    )
    tritanium = EveType.objects.create(id=34, name="Tritanium", group=mineral)
    EveTypeMaterial.objects.create(type=ore, material=tritanium, quantity=400)
    return ore


@pytest.mark.django_db
def test_portion_size_defaults_to_one():
    """Most types reprocess singly; only raw ore batches."""
    category = EveCategory.objects.create(id=4, name="Material")
    group = EveGroup.objects.create(id=18, name="Mineral", category=category)

    assert EveType.objects.create(id=34, name="Tritanium", group=group).portion_size == 1


@pytest.mark.django_db
def test_materials_are_reachable_from_the_type(veldspar):
    rows = list(veldspar.materials.all())

    assert len(rows) == 1
    assert rows[0].material.name == "Tritanium"
    assert rows[0].quantity == 400


@pytest.mark.django_db
def test_the_reverse_relation_finds_what_reprocesses_into_a_material(veldspar):
    tritanium = EveType.objects.get(id=34)

    assert [row.type.name for row in tritanium.reprocesses_from.all()] == ["Veldspar"]


@pytest.mark.django_db
def test_a_type_cannot_list_the_same_material_twice(veldspar):
    """EVERef keys materials by id, so a duplicate means an import bug."""
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        EveTypeMaterial.objects.create(
            type=veldspar, material=EveType.objects.get(id=34), quantity=1
        )
