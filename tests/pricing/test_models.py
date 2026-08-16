# tests/pricing/test_models.py
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from catalog.models import EveCategory, EveGroup, EveType
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule


@pytest.fixture
def ship_hierarchy(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    raven = EveType.objects.create(id=638, name="Raven", group=battleship)
    return ship, battleship, raven


@pytest.mark.django_db
def test_category_default_percent_is_unique_per_category(ship_hierarchy):
    ship, _, _ = ship_hierarchy
    CategoryDefaultPercent.objects.create(category=ship, percent=Decimal("80.00"))

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CategoryDefaultPercent.objects.create(category=ship, percent=Decimal("70.00"))


@pytest.mark.django_db
def test_custom_rule_targets_multiple_levels(ship_hierarchy):
    ship, battleship, raven = ship_hierarchy
    rule = CustomRule.objects.create(label="Mixed", percent=Decimal("75.00"))
    rule.categories.add(ship)
    rule.groups.add(battleship)
    rule.types.add(raven)

    assert rule.categories.count() == 1
    assert rule.types.first().name == "Raven"


@pytest.mark.django_db
def test_blacklist_entry_requires_exactly_one_target(ship_hierarchy):
    ship, battleship, _ = ship_hierarchy

    with pytest.raises(ValidationError):
        BlacklistEntry(category=ship, group=battleship).full_clean()

    with pytest.raises(ValidationError):
        BlacklistEntry().full_clean()

    entry = BlacklistEntry(category=ship)
    entry.full_clean()  # must not raise


@pytest.mark.django_db
def test_blacklist_exactly_one_target_enforced_by_database(ship_hierarchy):
    ship, battleship, _ = ship_hierarchy

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BlacklistEntry.objects.create(category=ship, group=battleship)
