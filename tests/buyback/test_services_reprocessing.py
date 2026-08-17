"""Generating a quote that prices ore by reprocessing.

The gateway is a stub, so this exercises the real database reads, the real
resolution and the real persistence without touching Janice.
"""

from decimal import Decimal

import pytest

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.models import QuoteItem, QuoteItemMaterial
from buyback.services import generate_quote
from catalog.models import EveCategory, EveGroup, EveType, EveTypeMaterial
from pricing.models import CategoryDefaultPercent, ReprocessingRule

ICICLE, HEAVY_WATER, STRONTIUM = 16262, 16272, 16275


class StubGateway:
    """Returns a fixed appraisal and records which types were priced."""

    def __init__(self, prices):
        self._prices = prices
        self.priced = None

    def create_appraisal(self, raw_text):
        return AppraisalResult(
            code="ICE1",
            items=(
                AppraisalItem(
                    type_id=ICICLE,
                    name="Clear Icicle",
                    quantity=10000,
                    unit_price=Decimal("500"),
                ),
            ),
            failures=(),
        )

    def price_types(self, type_ids):
        self.priced = sorted(type_ids)
        return self._prices


@pytest.fixture
def ice_catalogue(db):
    asteroid = EveCategory.objects.create(id=25, name="Asteroid")
    material = EveCategory.objects.create(id=4, name="Material")
    ice_group = EveGroup.objects.create(id=465, name="Ice", category=asteroid)
    product = EveGroup.objects.create(id=423, name="Ice Product", category=material)

    icicle = EveType.objects.create(
        id=ICICLE, name="Clear Icicle", group=ice_group, portion_size=1
    )
    water = EveType.objects.create(id=HEAVY_WATER, name="Heavy Water", group=product)
    strontium = EveType.objects.create(
        id=STRONTIUM, name="Strontium Clathrates", group=product
    )
    EveTypeMaterial.objects.create(type=icicle, material=water, quantity=69)
    EveTypeMaterial.objects.create(type=icicle, material=strontium, quantity=1)

    CategoryDefaultPercent.objects.create(category=material, percent=Decimal("80.00"))
    rule = ReprocessingRule.objects.create(label="Ice", yield_rate=Decimal("0.9063"))
    rule.groups.add(ice_group)
    return icicle


@pytest.mark.django_db
def test_a_reprocessed_quote_stores_its_material_breakdown(ice_catalogue):
    gateway = StubGateway({HEAVY_WATER: Decimal("99.40"), STRONTIUM: Decimal("4236")})

    quote = generate_quote("Clear Icicle 10000", gateway=gateway)

    item = quote.items.get()
    assert item.price_source_kind == "REPROCESSED"
    assert item.price_source_label == "Ice"
    assert item.yield_rate_applied == Decimal("0.9063")
    assert item.portion_size_applied == 1
    assert {m.type_name for m in item.materials.all()} == {
        "Heavy Water",
        "Strontium Clathrates",
    }
    assert item.line_total == Decimal("80440287.84")
    assert quote.total_value == item.line_total


@pytest.mark.django_db
def test_only_the_needed_materials_are_priced(ice_catalogue):
    gateway = StubGateway({HEAVY_WATER: Decimal("99.40"), STRONTIUM: Decimal("4236")})

    generate_quote("Clear Icicle 10000", gateway=gateway)

    assert gateway.priced == [HEAVY_WATER, STRONTIUM]


@pytest.mark.django_db
def test_no_price_call_is_made_when_nothing_reprocesses(db):
    """A paste of ordinary items must not gain an extra HTTP round trip."""
    category = EveCategory.objects.create(id=6, name="Ship")
    group = EveGroup.objects.create(id=27, name="Battleship", category=category)
    EveType.objects.create(id=638, name="Raven", group=group)
    CategoryDefaultPercent.objects.create(category=category, percent=Decimal("80.00"))

    class RavenGateway(StubGateway):
        def create_appraisal(self, raw_text):
            return AppraisalResult(
                code="SHIP1",
                items=(
                    AppraisalItem(
                        type_id=638,
                        name="Raven",
                        quantity=1,
                        unit_price=Decimal("100"),
                    ),
                ),
                failures=(),
            )

    gateway = RavenGateway({})
    generate_quote("Raven", gateway=gateway)

    assert gateway.priced is None


@pytest.mark.django_db
def test_an_unpriced_material_is_stored_and_visible(ice_catalogue):
    """Strontium gets no price back from the gateway."""
    gateway = StubGateway({HEAVY_WATER: Decimal("99.40")})

    quote = generate_quote("Clear Icicle 10000", gateway=gateway)

    unpriced = QuoteItemMaterial.objects.get(is_unpriced=True)
    assert unpriced.type_name == "Strontium Clathrates"
    assert unpriced.quantity == 9063
    assert unpriced.line_total == Decimal("0.00")
    assert quote.total_value > 0, "the rest of the line is still paid"


@pytest.mark.django_db
def test_editing_the_rule_afterwards_does_not_change_the_quote(ice_catalogue):
    """The frozen-quote guarantee, for the reprocessing basis."""
    gateway = StubGateway({HEAVY_WATER: Decimal("99.40"), STRONTIUM: Decimal("4236")})
    quote = generate_quote("Clear Icicle 10000", gateway=gateway)
    before = quote.total_value

    ReprocessingRule.objects.filter(label="Ice").update(yield_rate=Decimal("0.5000"))
    CategoryDefaultPercent.objects.filter(category_id=4).update(
        percent=Decimal("10.00")
    )

    reloaded = QuoteItem.objects.get(quote=quote)
    assert reloaded.quote.total_value == before
    assert reloaded.yield_rate_applied == Decimal("0.9063")
    assert reloaded.materials.get(type_id=HEAVY_WATER).percent_applied == Decimal(
        "80.00"
    )


@pytest.mark.django_db
def test_materials_attach_to_the_right_line_in_a_mixed_paste(ice_catalogue):
    """Persistence zips bulk_create's return value against the domain lines.

    A misaligned zip would hang Heavy Water off the Raven. The reprocessed line
    is deliberately FIRST: with it in the middle of three lines, reversing the
    zip maps that index to itself and the mutation goes undetected — which is
    exactly what happened when this test was first written.
    """
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    EveType.objects.create(id=638, name="Raven", group=battleship)
    CategoryDefaultPercent.objects.create(category=ship, percent=Decimal("50.00"))

    class MixedGateway(StubGateway):
        def create_appraisal(self, raw_text):
            return AppraisalResult(
                code="MIX1",
                items=(
                    AppraisalItem(
                        type_id=ICICLE, name="Clear Icicle", quantity=10000,
                        unit_price=Decimal("500"),
                    ),
                    AppraisalItem(
                        type_id=638, name="Raven", quantity=1,
                        unit_price=Decimal("100000000"),
                    ),
                ),
                failures=("junk line",),
            )

    gateway = MixedGateway(
        {HEAVY_WATER: Decimal("99.40"), STRONTIUM: Decimal("4236")}
    )
    quote = generate_quote("Raven\nClear Icicle 10000\njunk line", gateway=gateway)

    raven = quote.items.get(type_id=638)
    icicle = quote.items.get(type_id=ICICLE)

    assert list(raven.materials.all()) == [], "a market-priced line has no materials"
    assert icicle.materials.count() == 2
    assert {m.type_name for m in icicle.materials.all()} == {
        "Heavy Water", "Strontium Clathrates"
    }
    # And the unparseable failure line, which carries no type_id, is untouched.
    assert quote.items.filter(type_id__isnull=True).get().materials.count() == 0
