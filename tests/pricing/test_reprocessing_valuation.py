"""The reprocessing truth table. No database, no network, no clock.

Numbers come from the real data: Clear Icicle yields 69 Heavy Water, 35 Liquid
Ozone, 414 Helium Isotopes and 1 Strontium Clathrate per unit, portion_size 1.
Veldspar yields 400 Tritanium per 100-unit batch.
"""

from decimal import Decimal

from pricing.domain.decisions import FlagReason, PriceDecision, PriceSourceKind
from pricing.domain.reprocessing import (
    MaterialYield,
    ReprocessingInput,
    value_by_reprocessing,
)

HEAVY_WATER, OZONE, HELIUM, STRONTIUM = 16272, 16273, 16274, 16275
TRITANIUM = 34

NAMES = {
    HEAVY_WATER: "Heavy Water",
    OZONE: "Liquid Ozone",
    HELIUM: "Helium Isotopes",
    STRONTIUM: "Strontium Clathrates",
    TRITANIUM: "Tritanium",
}
PRICES = {
    HEAVY_WATER: Decimal("99.40"),
    OZONE: Decimal("85.99"),
    HELIUM: Decimal("742"),
    STRONTIUM: Decimal("4236"),
    TRITANIUM: Decimal("5.00"),
}


def paid(percent="80.00"):
    return PriceDecision(
        percent=Decimal(percent),
        source_kind=PriceSourceKind.CATEGORY_DEFAULT,
    )


def unruled():
    return PriceDecision(
        percent=Decimal("0"),
        source_kind=PriceSourceKind.NONE,
        flagged=True,
        flag_reason=FlagReason.NO_RULE,
    )


def blacklisted():
    return PriceDecision(
        percent=Decimal("0"),
        source_kind=PriceSourceKind.BLACKLIST,
        flagged=True,
        flag_reason=FlagReason.BLACKLISTED,
    )


ICICLE_OUTPUTS = (
    MaterialYield(type_id=HEAVY_WATER, quantity_per_batch=69),
    MaterialYield(type_id=OZONE, quantity_per_batch=35),
    MaterialYield(type_id=HELIUM, quantity_per_batch=414),
    MaterialYield(type_id=STRONTIUM, quantity_per_batch=1),
)


def icicle(quantity=10000, yield_rate="0.9063"):
    return ReprocessingInput(
        type_id=16262,
        quantity=quantity,
        portion_size=1,
        yield_rate=Decimal(yield_rate),
        outputs=ICICLE_OUTPUTS,
    )


def veldspar(quantity=10000, yield_rate="0.8734"):
    return ReprocessingInput(
        type_id=1230,
        quantity=quantity,
        portion_size=100,
        yield_rate=Decimal(yield_rate),
        outputs=(MaterialYield(type_id=TRITANIUM, quantity_per_batch=400),),
    )


def value(spec, decisions=None, prices=None):
    keys = [output.type_id for output in spec.outputs]
    return value_by_reprocessing(
        spec,
        market_prices=prices if prices is not None else {k: PRICES[k] for k in keys},
        decisions=decisions or {k: paid() for k in keys},
        material_names=NAMES,
    )


def test_ice_reprocesses_every_unit_with_no_remainder():
    result = value(icicle())

    assert result.batches == 10000
    assert result.remainder == 0
    assert not result.is_flagged


def test_units_are_floored_once_over_the_whole_lot():
    """floor(69 x 10000 x 0.9063) = 625 347, not floor(69 x 0.9063) x 10000."""
    result = value(icicle())
    recovered = {m.type_id: m.quantity for m in result.materials}

    assert recovered[HEAVY_WATER] == 625_347
    assert recovered[OZONE] == 317_205
    assert recovered[HELIUM] == 3_752_082


def test_a_material_yielding_one_per_batch_is_not_zeroed():
    """The regression that matters most: rounding per batch gives
    floor(1 x 0.9063) = 0, wiping Strontium Clathrates and 1.41% of the total."""
    result = value(icicle())
    recovered = {m.type_id: m.quantity for m in result.materials}

    assert recovered[STRONTIUM] == 9_063


def test_each_material_is_discounted_by_its_own_percentage():
    result = value(
        icicle(),
        decisions={
            HEAVY_WATER: paid("80.00"),
            OZONE: paid("80.00"),
            HELIUM: paid("90.00"),
            STRONTIUM: paid("80.00"),
        },
    )
    by_id = {m.type_id: m for m in result.materials}

    assert by_id[HELIUM].percent_applied == Decimal("90.00")
    assert by_id[HELIUM].line_total == Decimal("2505640359.60")
    assert by_id[HEAVY_WATER].line_total == Decimal("49727593.44")
    assert result.total == Decimal("2607901813.80")


def test_the_total_is_the_sum_of_the_material_lines():
    result = value(icicle())

    assert result.total == sum(m.line_total for m in result.materials)


def test_material_names_are_carried_for_display():
    result = value(icicle())

    assert {m.type_name for m in result.materials} == {
        "Heavy Water",
        "Liquid Ozone",
        "Helium Isotopes",
        "Strontium Clathrates",
    }


def test_an_unruled_material_is_recorded_but_not_paid():
    result = value(
        icicle(),
        decisions={
            **{k: paid() for k in (HEAVY_WATER, OZONE, HELIUM)},
            STRONTIUM: unruled(),
        },
    )
    strontium = next(m for m in result.materials if m.type_id == STRONTIUM)

    assert strontium.is_unpriced is True
    assert strontium.line_total == Decimal("0.00")
    assert strontium.quantity == 9_063, "still shown, so the gap is visible"
    assert result.total > 0, "the rest of the line is still paid"


def test_a_blacklisted_material_contributes_nothing_without_being_unpriced():
    """Blacklisting is deliberate, so it is not reported as a missing rule."""
    result = value(
        icicle(),
        decisions={
            **{k: paid() for k in (HEAVY_WATER, OZONE, HELIUM)},
            STRONTIUM: blacklisted(),
        },
    )
    strontium = next(m for m in result.materials if m.type_id == STRONTIUM)

    assert strontium.is_unpriced is False
    assert strontium.line_total == Decimal("0.00")


def test_a_material_with_no_market_price_is_unpriced():
    """The pricer returned no row for it; assuming free would be worse."""
    prices = {k: PRICES[k] for k in (HEAVY_WATER, OZONE, HELIUM)}
    result = value(icicle(), prices=prices)
    strontium = next(m for m in result.materials if m.type_id == STRONTIUM)

    assert strontium.is_unpriced is True
    assert strontium.line_total == Decimal("0.00")


def test_raw_ore_reprocesses_in_batches_of_its_portion_size():
    result = value(veldspar(quantity=10000))

    assert result.batches == 100
    assert result.remainder == 0
    # floor(400 x 100 x 0.8734) = 34 936
    assert result.materials[0].quantity == 34_936


def test_a_partial_batch_is_left_as_remainder():
    result = value(veldspar(quantity=10050))

    assert result.batches == 100
    assert result.remainder == 50
    assert not result.is_flagged, "the reprocessable part is still paid"


def test_less_than_one_batch_is_flagged_rather_than_quoted_at_zero():
    result = value(veldspar(quantity=50))

    assert result.batches == 0
    assert result.remainder == 50
    assert result.is_flagged
    assert result.flag_reason is FlagReason.BELOW_PORTION_SIZE
    assert result.total == Decimal("0.00")


def test_a_zero_yield_rate_is_flagged_rather_than_quoted_at_zero():
    """A misconfigured rule should be obvious, not a silent 0 ISK offer."""
    result = value(icicle(yield_rate="0"))

    assert result.is_flagged
    assert result.flag_reason is FlagReason.ZERO_YIELD
    assert result.total == Decimal("0.00")


def test_a_type_with_no_outputs_is_flagged():
    spec = ReprocessingInput(
        type_id=999,
        quantity=100,
        portion_size=1,
        yield_rate=Decimal("0.9"),
        outputs=(),
    )

    result = value_by_reprocessing(
        spec, market_prices={}, decisions={}, material_names={}
    )

    assert result.is_flagged
    assert result.total == Decimal("0.00")
