from datetime import datetime, timezone
from decimal import Decimal

import pytest

from pricing.domain.decisions import PriceSourceKind
from pricing.domain.resolution import resolve_price
from pricing.domain.ruleset import ItemClassification, Rule, RuleSet

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

RAVEN = ItemClassification(type_id=638, group_id=27, category_id=6)
APOCALYPSE = ItemClassification(type_id=642, group_id=27, category_id=6)
TRISTAN = ItemClassification(type_id=593, group_id=25, category_id=6)
RIFTER = ItemClassification(type_id=587, group_id=25, category_id=6)
TRITANIUM = ItemClassification(type_id=34, group_id=18, category_id=4)

BATTLESHIPS = Rule(
    label="Battleships",
    percent=Decimal("70.00"),
    group_ids=frozenset({27}),
)
RAVEN_SPECIAL = Rule(
    label="Raven Special",
    percent=Decimal("96.00"),
    type_ids=frozenset({638}),
)
SUMMER_SALE = Rule(
    label="Summer",
    percent=Decimal("90.00"),
    group_ids=frozenset({27}),
    valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
    valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
)
EXPIRED_SALE = Rule(
    label="Spring",
    percent=Decimal("95.00"),
    group_ids=frozenset({27}),
    valid_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
    valid_to=datetime(2026, 3, 31, tzinfo=timezone.utc),
)


def build_ruleset(*, sales=(), blacklist_type_ids=frozenset()):
    return RuleSet(
        blacklist_type_ids=blacklist_type_ids,
        sales=sales,
        custom_rules=(BATTLESHIPS, RAVEN_SPECIAL),
        category_defaults={6: Decimal("80.00")},
    )


def test_type_rule_wins_when_no_sale_active():
    decision = resolve_price(RAVEN, build_ruleset(sales=(EXPIRED_SALE,)), NOW)

    assert decision.percent == Decimal("96.00")
    assert decision.source_kind is PriceSourceKind.CUSTOM
    assert decision.source_label == "Raven Special"
    assert decision.flagged is False


def test_active_sale_beats_more_specific_custom_rule():
    """Tier beats specificity: a group-level sale outranks a type-level rule."""
    decision = resolve_price(RAVEN, build_ruleset(sales=(SUMMER_SALE,)), NOW)

    assert decision.percent == Decimal("90.00")
    assert decision.source_kind is PriceSourceKind.SALE


def test_group_rule_applies_when_no_type_rule():
    decision = resolve_price(APOCALYPSE, build_ruleset(), NOW)

    assert decision.percent == Decimal("70.00")
    assert decision.source_kind is PriceSourceKind.CUSTOM


def test_sale_applies_to_group_member_without_custom_type_rule():
    decision = resolve_price(APOCALYPSE, build_ruleset(sales=(SUMMER_SALE,)), NOW)

    assert decision.percent == Decimal("90.00")
    assert decision.source_kind is PriceSourceKind.SALE


def test_category_default_applies_when_no_rule_matches():
    decision = resolve_price(TRISTAN, build_ruleset(), NOW)

    assert decision.percent == Decimal("80.00")
    assert decision.source_kind is PriceSourceKind.CATEGORY_DEFAULT


def test_blacklist_beats_active_sale():
    ruleset = build_ruleset(
        sales=(SUMMER_SALE,), blacklist_type_ids=frozenset({587})
    )
    decision = resolve_price(RIFTER, ruleset, NOW)

    assert decision.percent == Decimal("0")
    assert decision.source_kind is PriceSourceKind.BLACKLIST
    assert decision.flagged is True
    assert decision.flag_reason == "Blacklisted"


def test_missing_category_default_is_flagged_not_an_error():
    decision = resolve_price(TRITANIUM, build_ruleset(), NOW)

    assert decision.percent == Decimal("0")
    assert decision.source_kind is PriceSourceKind.NONE
    assert decision.flagged is True
    assert decision.flag_reason == "No rule configured"


def test_most_specific_sale_wins_within_the_sale_tier():
    type_sale = Rule(
        label="Raven Weekend",
        percent=Decimal("99.00"),
        type_ids=frozenset({638}),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    decision = resolve_price(RAVEN, build_ruleset(sales=(SUMMER_SALE, type_sale)), NOW)

    assert decision.percent == Decimal("99.00")
    assert decision.source_label == "Raven Weekend"


@pytest.mark.parametrize(
    "item,expected",
    [
        (RAVEN, Decimal("96.00")),
        (APOCALYPSE, Decimal("70.00")),
        (TRISTAN, Decimal("80.00")),
    ],
)
def test_spec_table_without_sales(item, expected):
    assert resolve_price(item, build_ruleset(), NOW).percent == expected


def test_custom_rule_tie_break_prefers_higher_percent_first_order():
    """Same-level tie: highest percent wins, not iteration/tuple order (Fix 1)."""
    low = Rule(label="Low", percent=Decimal("60.00"), type_ids=frozenset({638}))
    high = Rule(label="High", percent=Decimal("85.00"), type_ids=frozenset({638}))

    ruleset = RuleSet(custom_rules=(low, high), category_defaults={6: Decimal("80.00")})
    decision = resolve_price(RAVEN, ruleset, NOW)

    assert decision.percent == Decimal("85.00")
    assert decision.source_label == "High"


def test_custom_rule_tie_break_prefers_higher_percent_second_order():
    """Identical tie to the test above with the tuple order reversed — the
    result must not change, proving the outcome isn't order-dependent."""
    low = Rule(label="Low", percent=Decimal("60.00"), type_ids=frozenset({638}))
    high = Rule(label="High", percent=Decimal("85.00"), type_ids=frozenset({638}))

    ruleset = RuleSet(custom_rules=(high, low), category_defaults={6: Decimal("80.00")})
    decision = resolve_price(RAVEN, ruleset, NOW)

    assert decision.percent == Decimal("85.00")
    assert decision.source_label == "High"


def test_sale_tie_break_prefers_higher_percent_first_order():
    """Reproduces the reported bug: two overlapping active sales on the same
    type must resolve to the higher percent (99%), not whichever the DB
    ordering (SaleRule.Meta.ordering = ["-valid_from"]) happened to put
    first."""
    sale_85 = Rule(
        label="Sale 85",
        percent=Decimal("85.00"),
        type_ids=frozenset({638}),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    sale_99 = Rule(
        label="Sale 99",
        percent=Decimal("99.00"),
        type_ids=frozenset({638}),
        valid_from=datetime(2026, 8, 10, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )

    decision = resolve_price(RAVEN, build_ruleset(sales=(sale_85, sale_99)), NOW)

    assert decision.percent == Decimal("99.00")
    assert decision.source_label == "Sale 99"


def test_sale_tie_break_prefers_higher_percent_second_order():
    """Identical tie to the test above with the tuple order reversed — the
    result must not change, proving the outcome isn't order-dependent."""
    sale_85 = Rule(
        label="Sale 85",
        percent=Decimal("85.00"),
        type_ids=frozenset({638}),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    sale_99 = Rule(
        label="Sale 99",
        percent=Decimal("99.00"),
        type_ids=frozenset({638}),
        valid_from=datetime(2026, 8, 10, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )

    decision = resolve_price(RAVEN, build_ruleset(sales=(sale_99, sale_85)), NOW)

    assert decision.percent == Decimal("99.00")
    assert decision.source_label == "Sale 99"


def test_specificity_still_beats_percent_across_levels():
    """Regression: specificity remains absolute across levels. A type-level
    rule at 10% must still beat a group-level rule at 90% — percent only
    breaks ties WITHIN a level, it never promotes a less specific rule."""
    type_rule = Rule(label="Type Rule", percent=Decimal("10.00"), type_ids=frozenset({638}))
    group_rule = Rule(label="Group Rule", percent=Decimal("90.00"), group_ids=frozenset({27}))

    ruleset_a = RuleSet(
        custom_rules=(group_rule, type_rule), category_defaults={6: Decimal("80.00")}
    )
    ruleset_b = RuleSet(
        custom_rules=(type_rule, group_rule), category_defaults={6: Decimal("80.00")}
    )

    for ruleset in (ruleset_a, ruleset_b):
        decision = resolve_price(RAVEN, ruleset, NOW)
        assert decision.percent == Decimal("10.00")
        assert decision.source_label == "Type Rule"
