"""The seller must be able to see why a reprocessed line is worth what it is."""

from decimal import Decimal

import pytest

from buyback.models import Quote, QuoteItem, QuoteItemMaterial


@pytest.fixture
def reprocessed_quote(db):
    quote = Quote.objects.create(
        code="ICE1", total_value=Decimal("80440287.84"), contract_to="Operator"
    )
    item = QuoteItem.objects.create(
        quote=quote,
        type_id=16262,
        type_name="Clear Icicle",
        quantity=10000,
        unit_price=Decimal("500.00"),
        percent_applied=Decimal("0.00"),
        price_source_kind="REPROCESSED",
        price_source_label="Ice",
        line_total=Decimal("80440287.84"),
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
    QuoteItemMaterial.objects.create(
        quote_item=item,
        type_id=16275,
        type_name="Strontium Clathrates",
        quantity=9063,
        unit_price=Decimal("0.00"),
        percent_applied=Decimal("0.00"),
        line_total=Decimal("0.00"),
        is_unpriced=True,
    )
    return quote


@pytest.mark.django_db
def test_the_page_lists_every_recovered_material(client, reprocessed_quote):
    body = client.get("/q/ICE1/").content.decode()

    assert "Heavy Water" in body
    assert "Strontium Clathrates" in body
    assert "625 347" in body, "quantities use the EVE space separator"


@pytest.mark.django_db
def test_the_page_says_the_line_was_priced_by_reprocessing(client, reprocessed_quote):
    body = client.get("/q/ICE1/").content.decode()

    assert "Reprocessed" in body
    assert "0.9063" in body, "the applied yield should be visible"


@pytest.mark.django_db
def test_an_unpriced_material_is_marked_as_not_paid(client, reprocessed_quote):
    """The visibility that makes "skip it" safe rather than a silent shortfall."""
    body = client.get("/q/ICE1/").content.decode()

    assert "not paid" in body.lower()


@pytest.mark.django_db
def test_a_market_priced_quote_shows_no_breakdown(client, db):
    quote = Quote.objects.create(code="ORE1", total_value=Decimal("100.00"))
    QuoteItem.objects.create(
        quote=quote,
        type_id=34,
        type_name="Tritanium",
        quantity=100,
        unit_price=Decimal("5.00"),
        percent_applied=Decimal("20.00"),
        price_source_kind="CATEGORY_DEFAULT",
        line_total=Decimal("100.00"),
    )

    body = client.get("/q/ORE1/").content.decode()

    assert "Reprocessed" not in body
    assert "not paid" not in body.lower()


@pytest.mark.django_db
def test_the_source_column_names_the_rule_not_the_word_reprocessed(
    client, reprocessed_quote
):
    """REPROCESSED is a NAMED_KIND, so the Source shows "Ice" — the operator's
    rule name — exactly as a custom rule or sale does."""
    from buyback.templatetags.buyback_labels import price_source_label

    item = QuoteItem.objects.get(quote=reprocessed_quote)

    assert price_source_label(item) == "Ice"
