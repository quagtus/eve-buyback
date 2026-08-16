import pytest

from catalog.models import EveCategory, EveGroup, EveType


@pytest.mark.django_db
def test_catalog_hierarchy_resolves_type_to_category():
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    raven = EveType.objects.create(id=638, name="Raven", group=battleship)

    assert raven.group.category.name == "Ship"
    assert str(raven) == "Raven"
