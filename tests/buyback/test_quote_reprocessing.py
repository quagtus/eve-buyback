"""Building quote lines for items priced by reprocessing.

Pure: build_quote takes the reprocessing inputs as data, so this needs no
database and no network.
"""

from datetime import datetime, timezone
from decimal import Decimal

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.domain.quote import build_quote
from pricing.domain.decisions import FlagReason, PriceSourceKind
from pricing.domain.reprocessing import MaterialYield
from pricing.domain.ruleset import (
    ItemClassification,
    ReprocessingRule,
    Rule,
    RuleSet,
)

NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)
ICICLE, HEAVY_WATER, STRONTIUM = 16262, 16272, 16275

CLASSIFICATIONS = {
    ICICLE: ItemClassification(type_id=ICICLE, group_id=465, category_id=25),
    HEAVY_WATER: ItemClassification(type_id=HEAVY_WATER, group_id=423, category_id=4),
    STRONTIUM: ItemClassification(type_id=STRONTIUM, group_id=423, category_id=4),
}
YIELDS = {
    ICICLE: (
        MaterialYield(type_id=HEAVY_WATER, quantity_per_batch=69),
        MaterialYield(type_id=STRONTIUM, quantity_per_batch=1),
    )
}
PORTION_SIZES = {ICICLE: 1}
NAMES = {HEAVY_WATER: "Heavy Water", STRONTIUM: "Strontium Clathrates"}
PRICES = {HEAVY_WATER: Decimal("99.40"), STRONTIUM: Decimal("4236")}

ICE_RULE = ReprocessingRule(
    label="Ice", yield_rate=Decimal("0.9063"), group_ids=frozenset({465})
)
MATERIAL_PCT = Rule(
    label="Materials", percent=Decimal("80.00"), category_ids=frozenset({4})
)


def appraisal(quantity=10000, unit_price="500"):
    return AppraisalResult(
        code="ICE1",
        items=(
            AppraisalItem(
                type_id=ICICLE,
                name="Clear Icicle",
                quantity=quantity,
                unit_price=Decimal(unit_price),
            ),
        ),
        failures=(),
    )


def build(ruleset, **overrides):
    kwargs = dict(
        appraisal=appraisal(),
        ruleset=ruleset,
        classifications=CLASSIFICATIONS,
        now=NOW,
        material_yields=YIELDS,
        portion_sizes=PORTION_SIZES,
        material_prices=PRICES,
        material_names=NAMES,
    )
    kwargs.update(overrides)
    return build_quote(**kwargs)


def test_a_reprocessed_line_is_valued_from_its_materials_not_its_own_price():
    """unit_price of 500 x 10 000 would be 5 000 000 at 80%; reprocessing gives
    far more, and the ore price must not appear in the total at all."""
    ruleset = RuleSet(custom_rules=(MATERIAL_PCT,), reprocessing_rules=(ICE_RULE,))

    quote = build(ruleset)
    line = quote.lines[0]

    assert line.price_source_kind == PriceSourceKind.REPROCESSED.value
    assert line.price_source_label == "Ice"
    assert line.yield_rate_applied == Decimal("0.9063")
    assert line.portion_size_applied == 1
    # 625 347 x 99.40 x 0.8 + 9 063 x 4236 x 0.8
    assert line.line_total == Decimal("80440287.84")
    assert quote.total_value == line.line_total


def test_the_material_breakdown_is_attached_to_the_line():
    ruleset = RuleSet(custom_rules=(MATERIAL_PCT,), reprocessing_rules=(ICE_RULE,))

    line = build(ruleset).lines[0]

    by_name = {m.type_name: m for m in line.materials}
    assert by_name["Heavy Water"].quantity == 625_347
    assert by_name["Heavy Water"].percent_applied == Decimal("80.00")
    assert by_name["Strontium Clathrates"].quantity == 9_063


def test_a_material_without_a_rule_is_recorded_as_unpriced():
    """Target the mineral group only, so the ice products stay unruled."""
    mineral_only = Rule(
        label="Minerals", percent=Decimal("80.00"), group_ids=frozenset({18})
    )
    ruleset = RuleSet(custom_rules=(mineral_only,), reprocessing_rules=(ICE_RULE,))

    line = build(ruleset).lines[0]

    assert all(m.is_unpriced for m in line.materials)
    assert line.line_total == Decimal("0.00")


def test_an_item_with_no_reprocessing_rule_is_priced_at_market_as_before():
    ruleset = RuleSet(
        custom_rules=(
            Rule(label="Ore", percent=Decimal("50.00"), category_ids=frozenset({25})),
        )
    )

    line = build(ruleset).lines[0]

    assert line.price_source_kind == PriceSourceKind.CUSTOM.value
    assert line.materials == ()
    assert line.yield_rate_applied is None
    assert line.line_total == Decimal("2500000.00")


def test_a_reprocessing_rule_with_no_yield_data_flags_the_line():
    """The rule matches but the catalogue has no materials for the type."""
    ruleset = RuleSet(custom_rules=(MATERIAL_PCT,), reprocessing_rules=(ICE_RULE,))

    line = build(ruleset, material_yields={}).lines[0]

    assert line.is_flagged
    assert line.line_total == Decimal("0.00")


def test_less_than_one_batch_flags_the_line():
    veldspar_rule = ReprocessingRule(
        label="Ore", yield_rate=Decimal("0.87"), category_ids=frozenset({25})
    )
    ruleset = RuleSet(
        custom_rules=(MATERIAL_PCT,), reprocessing_rules=(veldspar_rule,)
    )

    line = build(
        ruleset, appraisal=appraisal(quantity=50), portion_sizes={ICICLE: 100}
    ).lines[0]

    assert line.is_flagged
    assert line.flag_reason is FlagReason.BELOW_PORTION_SIZE
    assert line.line_total == Decimal("0.00")


def test_existing_callers_need_pass_no_reprocessing_arguments():
    """Backwards compatibility: build_quote must still work with four arguments,
    so nothing that does not price ore has to change."""
    quote = build_quote(
        appraisal(),
        RuleSet(
            custom_rules=(
                Rule(
                    label="Ore", percent=Decimal("50.00"), category_ids=frozenset({25})
                ),
            )
        ),
        CLASSIFICATIONS,
        NOW,
    )

    assert quote.lines[0].line_total == Decimal("2500000.00")
