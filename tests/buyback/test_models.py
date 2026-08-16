from decimal import Decimal

import pytest

from buyback.models import Snapshot, SnapshotItem


@pytest.mark.django_db
def test_snapshot_is_keyed_by_the_janice_code():
    snapshot = Snapshot.objects.create(
        code="4ovArs",
        total_value=Decimal("140.00"),
        contract_to="Buyback Corp",
        contract_instructions="Contract to Buyback Corp in Jita.",
    )

    assert snapshot.pk == "4ovArs"
    assert Snapshot.objects.get(pk="4ovArs").total_value == Decimal("140.00")


@pytest.mark.django_db
def test_snapshot_items_store_kind_and_label_separately():
    snapshot = Snapshot.objects.create(code="4ovArs", total_value=Decimal("140.00"))
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=638,
        type_name="Raven",
        quantity=2,
        unit_price=Decimal("100.00"),
        percent_applied=Decimal("70.00"),
        price_source_kind="CUSTOM",
        price_source_label="Battleships",
        line_total=Decimal("140.00"),
    )

    item = snapshot.items.get()
    assert item.price_source_kind == "CUSTOM"
    assert item.price_source_label == "Battleships"
    assert item.flag_reason_code is None
    assert item.is_flagged is False


@pytest.mark.django_db
def test_system_source_has_no_rule_label():
    snapshot = Snapshot.objects.create(code="abc", total_value=Decimal("0.00"))
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=587,
        type_name="Rifter",
        quantity=1,
        unit_price=Decimal("50.00"),
        percent_applied=Decimal("0.00"),
        price_source_kind="BLACKLIST",
        price_source_label="",
        line_total=Decimal("0.00"),
        is_flagged=True,
        flag_reason_code="BLACKLISTED",
    )

    item = snapshot.items.get()
    assert item.price_source_label == ""
    assert item.flag_reason_code == "BLACKLISTED"


@pytest.mark.django_db
def test_item_count_property():
    snapshot = Snapshot.objects.create(code="abc", total_value=Decimal("0.00"))
    for index in range(3):
        SnapshotItem.objects.create(
            snapshot=snapshot,
            type_id=index,
            type_name=f"Item {index}",
            quantity=1,
            unit_price=Decimal("1.00"),
            percent_applied=Decimal("100.00"),
            price_source_kind="CUSTOM",
            price_source_label="test",
            line_total=Decimal("1.00"),
        )

    assert snapshot.item_count == 3


@pytest.mark.django_db
def test_flagged_item_stores_its_reason():
    snapshot = Snapshot.objects.create(code="abc", total_value=Decimal("0.00"))
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=None,
        type_name="garbage line",
        quantity=0,
        unit_price=Decimal("0.00"),
        percent_applied=Decimal("0.00"),
        price_source_kind="NONE",
        line_total=Decimal("0.00"),
        is_flagged=True,
        flag_reason_code="UNPARSEABLE",
    )

    assert snapshot.items.get().flag_reason_code == "UNPARSEABLE"
