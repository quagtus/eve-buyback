# tests/pricing/test_repositories.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from catalog.models import EveCategory, EveGroup, EveType
from pricing.domain.decisions import PriceSourceKind
from pricing.domain.resolution import resolve_price
from pricing.domain.ruleset import ItemClassification
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule
from pricing.repositories import load_ruleset

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def hierarchy(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    frigate = EveGroup.objects.create(id=25, name="Frigate", category=ship)
    raven = EveType.objects.create(id=638, name="Raven", group=battleship)
    rifter = EveType.objects.create(id=587, name="Rifter", group=frigate)
    return {"ship": ship, "battleship": battleship, "raven": raven, "rifter": rifter}


@pytest.mark.django_db
def test_load_ruleset_round_trips_through_resolution(hierarchy):
    CategoryDefaultPercent.objects.create(
        category=hierarchy["ship"], percent=Decimal("80.00")
    )
    battleships = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    battleships.groups.add(hierarchy["battleship"])

    special = CustomRule.objects.create(label="Raven Special", percent=Decimal("96.00"))
    special.types.add(hierarchy["raven"])

    BlacklistEntry.objects.create(type=hierarchy["rifter"])

    ruleset = load_ruleset()

    raven = ItemClassification(type_id=638, group_id=27, category_id=6)
    assert resolve_price(raven, ruleset, NOW).percent == Decimal("96.00")

    rifter = ItemClassification(type_id=587, group_id=25, category_id=6)
    assert resolve_price(rifter, ruleset, NOW).source_kind is PriceSourceKind.BLACKLIST


@pytest.mark.django_db
def test_load_ruleset_includes_sales_with_windows(hierarchy):
    sale = SaleRule.objects.create(
        label="Summer",
        percent=Decimal("90.00"),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    sale.groups.add(hierarchy["battleship"])

    ruleset = load_ruleset()

    assert len(ruleset.sales) == 1
    assert ruleset.sales[0].label == "Summer"
    assert ruleset.sales[0].group_ids == frozenset({27})


@pytest.mark.django_db
def test_load_ruleset_on_empty_database_returns_empty_ruleset(db):
    ruleset = load_ruleset()

    assert ruleset.sales == ()
    assert ruleset.custom_rules == ()
    assert dict(ruleset.category_defaults) == {}
