from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from catalog.models import EveCategory, EveGroup, EveType
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule
from pricing.views import build_summary_rows

SUMMARY_URL = "/admin/pricing/summary/"


@pytest.fixture
def rules(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    raven = EveType.objects.create(id=638, name="Raven", group=battleship)

    CategoryDefaultPercent.objects.create(category=ship, percent=Decimal("80.00"))

    group_rule = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    group_rule.groups.add(battleship)

    type_rule = CustomRule.objects.create(label="Raven Special", percent=Decimal("96.00"))
    type_rule.types.add(raven)

    now = timezone.now()
    active = SaleRule.objects.create(
        label="Active Sale",
        percent=Decimal("90.00"),
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=1),
    )
    active.groups.add(battleship)

    expired = SaleRule.objects.create(
        label="Expired Sale",
        percent=Decimal("95.00"),
        valid_from=now - timedelta(days=30),
        valid_to=now - timedelta(days=10),
    )
    expired.groups.add(battleship)

    scheduled = SaleRule.objects.create(
        label="Future Sale",
        percent=Decimal("85.00"),
        valid_from=now + timedelta(days=10),
        valid_to=now + timedelta(days=20),
    )
    scheduled.groups.add(battleship)

    BlacklistEntry.objects.create(type=raven)
    return ship


@pytest.mark.django_db
def test_rows_are_ordered_most_specific_first(rules):
    rows = build_summary_rows(timezone.now())
    custom = [r for r in rows if r["kind"] == "Custom rule"]

    assert custom[0]["level"] == "Type"
    assert custom[-1]["level"] == "Group"


@pytest.mark.django_db
def test_sale_status_is_classified(rules):
    rows = build_summary_rows(timezone.now())
    statuses = {r["label"]: r["status"] for r in rows if r["kind"] == "Sale"}

    assert statuses["Active Sale"] == "active"
    assert statuses["Expired Sale"] == "expired"
    assert statuses["Future Sale"] == "scheduled"


@pytest.mark.django_db
def test_summary_includes_defaults_and_blacklist(rules):
    rows = build_summary_rows(timezone.now())
    kinds = {row["kind"] for row in rows}

    assert "Category default" in kinds
    assert "Blacklist" in kinds


@pytest.mark.django_db
def test_view_requires_staff_login(client, rules):
    anonymous = client.get(SUMMARY_URL)
    assert anonymous.status_code in (302, 403)

    User.objects.create_superuser("admin", "a@example.com", "password123")
    client.login(username="admin", password="password123")

    response = client.get(SUMMARY_URL)
    assert response.status_code == 200
    assert b"Raven Special" in response.content
