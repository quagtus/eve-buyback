"""A reprocessing rule targets items the same way a percentage rule does.

It carries a yield rate rather than a percent. Overloading Rule.percent to hold
0.9063 would be a trap: every other reader of that field means percentage points,
where 0.9063 is nine tenths of one percent.
"""

from decimal import Decimal

from pricing.domain.decisions import MatchLevel
from pricing.domain.ruleset import (
    ItemClassification,
    ReprocessingRule,
    Rule,
    RuleSet,
    match_level,
)

# Veldspar: type 1230, group 462, category 25
VELDSPAR = ItemClassification(type_id=1230, group_id=462, category_id=25)
# Clear Icicle: type 16262, group 465 (Ice), category 25
ICICLE = ItemClassification(type_id=16262, group_id=465, category_id=25)


def test_match_level_prefers_type_then_group_then_category():
    assert (
        match_level(VELDSPAR, category_ids={25}, group_ids=set(), type_ids=set())
        is MatchLevel.CATEGORY
    )
    assert (
        match_level(VELDSPAR, category_ids={25}, group_ids={462}, type_ids=set())
        is MatchLevel.GROUP
    )
    assert (
        match_level(VELDSPAR, category_ids={25}, group_ids={462}, type_ids={1230})
        is MatchLevel.TYPE
    )


def test_match_level_returns_none_when_nothing_targets_the_item():
    assert (
        match_level(VELDSPAR, category_ids={6}, group_ids=set(), type_ids=set()) is None
    )


def test_a_reprocessing_rule_matches_by_target():
    rule = ReprocessingRule(
        label="Ice", yield_rate=Decimal("0.9063"), group_ids=frozenset({465})
    )

    assert rule.match_level(ICICLE) is MatchLevel.GROUP
    assert rule.match_level(VELDSPAR) is None


def test_a_reprocessing_rule_ties_on_its_yield_rate():
    """_best_match breaks same-level ties on the higher value; for a reprocessing
    rule that has to be the yield, not a percent it does not have."""
    rule = ReprocessingRule(label="Ice", yield_rate=Decimal("0.9063"))

    assert rule.tie_break_value == Decimal("0.9063")


def test_a_percentage_rule_ties_on_its_percent():
    assert Rule(label="Ships", percent=Decimal("80.00")).tie_break_value == Decimal(
        "80.00"
    )


def test_a_ruleset_carries_reprocessing_rules():
    rule = ReprocessingRule(label="Ice", yield_rate=Decimal("0.9063"))

    assert RuleSet(reprocessing_rules=(rule,)).reprocessing_rules == (rule,)


def test_a_ruleset_defaults_to_no_reprocessing_rules():
    """Existing quotes must behave exactly as before this feature."""
    assert RuleSet().reprocessing_rules == ()
