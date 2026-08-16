from datetime import datetime, timezone
from decimal import Decimal

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.domain.quote import build_quote
from pricing.domain.ruleset import ItemClassification, Rule, RuleSet

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

CLASSIFICATIONS = {
    638: ItemClassification(type_id=638, group_id=27, category_id=6),
    587: ItemClassification(type_id=587, group_id=25, category_id=6),
    34: ItemClassification(type_id=34, group_id=18, category_id=4),
}

RULESET = RuleSet(
    blacklist_type_ids=frozenset({587}),
    custom_rules=(
        Rule(label="Battleships", percent=Decimal("70.00"), group_ids=frozenset({27})),
    ),
    category_defaults={6: Decimal("80.00")},
)


def appraisal(items, failures=()):
    return AppraisalResult(code="4ovArs", items=tuple(items), failures=tuple(failures))


def test_prices_a_normal_line():
    result = appraisal(
        [AppraisalItem(type_id=638, name="Raven", quantity=2, unit_price=Decimal("100.00"))]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    line = quote.lines[0]
    assert line.percent_applied == Decimal("70.00")
    assert line.line_total == Decimal("140.00")
    assert line.is_flagged is False
    assert quote.total_value == Decimal("140.00")


def test_blacklisted_line_is_flagged_and_contributes_nothing():
    result = appraisal(
        [
            AppraisalItem(type_id=638, name="Raven", quantity=1, unit_price=Decimal("100.00")),
            AppraisalItem(type_id=587, name="Rifter", quantity=5, unit_price=Decimal("50.00")),
        ]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    rifter = quote.lines[1]
    assert rifter.is_flagged is True
    assert rifter.flag_reason == "Blacklisted"
    assert rifter.line_total == Decimal("0.00")
    assert quote.total_value == Decimal("70.00")


def test_item_missing_from_catalog_is_flagged_not_crashed():
    result = appraisal(
        [AppraisalItem(type_id=99999, name="Mystery", quantity=1, unit_price=Decimal("10.00"))]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert quote.lines[0].is_flagged is True
    assert quote.lines[0].flag_reason == "Unrecognized item"
    assert quote.total_value == Decimal("0.00")


def test_category_without_default_is_flagged():
    result = appraisal(
        [AppraisalItem(type_id=34, name="Tritanium", quantity=100, unit_price=Decimal("5.00"))]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert quote.lines[0].is_flagged is True
    assert quote.lines[0].flag_reason == "No rule configured"


def test_janice_failures_become_flagged_zero_value_lines():
    result = appraisal(
        [AppraisalItem(type_id=638, name="Raven", quantity=1, unit_price=Decimal("100.00"))],
        failures=["definitely not an item"],
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert len(quote.lines) == 2
    failure_line = quote.lines[-1]
    assert failure_line.type_name == "definitely not an item"
    assert failure_line.type_id is None
    assert failure_line.is_flagged is True
    assert failure_line.flag_reason == "Could not be parsed"
    assert failure_line.line_total == Decimal("0.00")


def test_total_equals_the_sum_of_displayed_lines():
    result = appraisal(
        [
            AppraisalItem(type_id=638, name="Raven", quantity=1, unit_price=Decimal("0.333")),
            AppraisalItem(type_id=638, name="Raven", quantity=1, unit_price=Decimal("0.333")),
        ]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert quote.total_value == sum(line.line_total for line in quote.lines)
