from datetime import datetime, timezone
from decimal import Decimal

import pytest

from catalog.models import EveCategory, EveGroup
from pricing.admin import CustomRuleForm, SaleRuleForm
from pricing.models import CustomRule, SaleRule


@pytest.fixture
def hierarchy(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    frigate = EveGroup.objects.create(id=25, name="Frigate", category=ship)
    return ship, battleship, frigate


@pytest.mark.django_db
def test_rejects_a_custom_rule_overlapping_an_existing_one(hierarchy):
    _, battleship, _ = hierarchy
    existing = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    existing.groups.add(battleship)

    form = CustomRuleForm(
        data={"label": "Dupe", "percent": "60.00", "groups": [battleship.pk]}
    )

    assert form.is_valid() is False
    assert "Battleships" in str(form.errors)


@pytest.mark.django_db
def test_allows_a_rule_at_a_different_level(hierarchy):
    ship, battleship, _ = hierarchy
    existing = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    existing.groups.add(battleship)

    form = CustomRuleForm(
        data={"label": "Ships", "percent": "80.00", "categories": [ship.pk]}
    )

    assert form.is_valid() is True


@pytest.mark.django_db
def test_editing_a_rule_does_not_conflict_with_itself(hierarchy):
    _, battleship, _ = hierarchy
    existing = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    existing.groups.add(battleship)

    form = CustomRuleForm(
        instance=existing,
        data={"label": "Battleships", "percent": "75.00", "groups": [battleship.pk]},
    )

    assert form.is_valid() is True


@pytest.mark.django_db
def test_sales_with_disjoint_windows_are_allowed(hierarchy):
    _, battleship, _ = hierarchy
    august = SaleRule.objects.create(
        label="August",
        percent=Decimal("90.00"),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    august.groups.add(battleship)

    form = SaleRuleForm(
        data={
            "label": "September",
            "percent": "92.00",
            "groups": [battleship.pk],
            "valid_from": "2026-09-01 00:00:00",
            "valid_to": "2026-09-30 00:00:00",
        }
    )

    assert form.is_valid() is True


@pytest.mark.django_db
def test_sales_with_overlapping_windows_are_rejected(hierarchy):
    _, battleship, _ = hierarchy
    august = SaleRule.objects.create(
        label="August",
        percent=Decimal("90.00"),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    august.groups.add(battleship)

    form = SaleRuleForm(
        data={
            "label": "Overlapping",
            "percent": "92.00",
            "groups": [battleship.pk],
            "valid_from": "2026-08-15 00:00:00",
            "valid_to": "2026-09-15 00:00:00",
        }
    )

    assert form.is_valid() is False
    assert "August" in str(form.errors)
