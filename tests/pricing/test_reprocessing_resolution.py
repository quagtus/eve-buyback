"""Which reprocessing rule applies to an item, if any."""

from decimal import Decimal

from pricing.domain.resolution import resolve_reprocessing
from pricing.domain.ruleset import ItemClassification, ReprocessingRule, RuleSet

VELDSPAR = ItemClassification(type_id=1230, group_id=462, category_id=25)
ICICLE = ItemClassification(type_id=16262, group_id=465, category_id=25)
RAVEN = ItemClassification(type_id=638, group_id=27, category_id=6)

ORE = ReprocessingRule(
    label="Ore", yield_rate=Decimal("0.8734"), category_ids=frozenset({25})
)
ICE = ReprocessingRule(
    label="Ice", yield_rate=Decimal("0.9063"), group_ids=frozenset({465})
)


def test_no_rules_means_no_reprocessing():
    assert resolve_reprocessing(VELDSPAR, RuleSet()) is None


def test_an_unmatched_item_is_not_reprocessed():
    assert resolve_reprocessing(RAVEN, RuleSet(reprocessing_rules=(ORE, ICE))) is None


def test_a_category_rule_matches_ore():
    rule = resolve_reprocessing(VELDSPAR, RuleSet(reprocessing_rules=(ORE,)))

    assert rule is not None
    assert rule.yield_rate == Decimal("0.8734")


def test_the_group_rule_beats_the_category_rule_for_ice():
    """The requirement: ice reprocesses at a different rate from other ore.
    Ice matches at Group, Asteroid at Category, and specificity settles it."""
    rule = resolve_reprocessing(ICICLE, RuleSet(reprocessing_rules=(ORE, ICE)))

    assert rule.label == "Ice"
    assert rule.yield_rate == Decimal("0.9063")


def test_rule_order_does_not_change_the_outcome():
    forward = resolve_reprocessing(ICICLE, RuleSet(reprocessing_rules=(ORE, ICE)))
    reverse = resolve_reprocessing(ICICLE, RuleSet(reprocessing_rules=(ICE, ORE)))

    assert forward.label == reverse.label == "Ice"


def test_a_same_level_tie_takes_the_higher_yield():
    """Defensive: the admin form blocks same-level overlaps, but a direct ORM
    write can still produce two. Iteration order must not decide the payout."""
    low = ReprocessingRule(
        label="Low", yield_rate=Decimal("0.50"), group_ids=frozenset({465})
    )
    high = ReprocessingRule(
        label="High", yield_rate=Decimal("0.90"), group_ids=frozenset({465})
    )

    assert (
        resolve_reprocessing(ICICLE, RuleSet(reprocessing_rules=(low, high))).label
        == "High"
    )
    assert (
        resolve_reprocessing(ICICLE, RuleSet(reprocessing_rules=(high, low))).label
        == "High"
    )
