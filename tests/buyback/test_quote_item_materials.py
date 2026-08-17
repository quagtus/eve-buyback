"""The reprocessing breakdown is frozen with the quote, like everything else.

A quote page states "This page is permanent and will not change". Recomputing the
breakdown at render time would break that the first time a rule was edited.
"""

from decimal import Decimal

import pytest

from buyback.models import Quote, QuoteItem, QuoteItemMaterial


@pytest.fixture
def reprocessed_line(db):
    quote = Quote.objects.create(code="ICE1", total_value=Decimal("100.00"))
    item = QuoteItem.objects.create(
        quote=quote,
        type_id=16262,
        type_name="Clear Icicle",
        quantity=10000,
        unit_price=Decimal("0.00"),
        percent_applied=Decimal("0.00"),
        price_source_kind="REPROCESSED",
        line_total=Decimal("100.00"),
        yield_rate_applied=Decimal("0.9063"),
        portion_size_applied=1,
    )
    QuoteItemMaterial.objects.create(
        quote_item=item,
        type_id=16272,
        type_name="Heavy Water",
        quantity=625347,
        unit_price=Decimal("99.40"),
        percent_applied=Decimal("80.00"),
        line_total=Decimal("49727593.44"),
    )
    return item


@pytest.mark.django_db
def test_materials_hang_off_the_quote_item(reprocessed_line):
    materials = list(reprocessed_line.materials.all())

    assert len(materials) == 1
    assert materials[0].type_name == "Heavy Water"
    assert materials[0].quantity == 625347


@pytest.mark.django_db
def test_the_applied_yield_and_portion_size_are_frozen(reprocessed_line):
    """Editing the rule afterwards must not change what the quote claims."""
    assert reprocessed_line.yield_rate_applied == Decimal("0.9063")
    assert reprocessed_line.portion_size_applied == 1


@pytest.mark.django_db
def test_a_material_defaults_to_priced(reprocessed_line):
    assert reprocessed_line.materials.get().is_unpriced is False


@pytest.mark.django_db
def test_an_unpriced_material_is_recorded_with_zero_total(reprocessed_line):
    """Shown so a forgotten mineral rule is visible, not silently absent."""
    QuoteItemMaterial.objects.create(
        quote_item=reprocessed_line,
        type_id=16275,
        type_name="Strontium Clathrates",
        quantity=9063,
        unit_price=Decimal("0.00"),
        percent_applied=Decimal("0.00"),
        line_total=Decimal("0.00"),
        is_unpriced=True,
    )

    unpriced = reprocessed_line.materials.get(is_unpriced=True)
    assert unpriced.type_name == "Strontium Clathrates"
    assert unpriced.line_total == Decimal("0.00")


@pytest.mark.django_db
def test_materials_are_removed_with_their_quote(reprocessed_line):
    Quote.objects.filter(code="ICE1").delete()

    assert QuoteItemMaterial.objects.count() == 0


@pytest.mark.django_db
def test_a_non_reprocessed_line_needs_no_yield(db):
    """Every existing quote line has these unset, so they must be nullable."""
    quote = Quote.objects.create(code="ORE1", total_value=Decimal("1.00"))
    item = QuoteItem.objects.create(
        quote=quote,
        type_id=34,
        type_name="Tritanium",
        quantity=1,
        unit_price=Decimal("1.00"),
        percent_applied=Decimal("100.00"),
        price_source_kind="CATEGORY_DEFAULT",
        line_total=Decimal("1.00"),
    )

    assert item.yield_rate_applied is None
    assert item.portion_size_applied is None
    assert list(item.materials.all()) == []
