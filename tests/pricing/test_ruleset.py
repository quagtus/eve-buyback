from datetime import datetime, timezone
from decimal import Decimal

from pricing.domain.decisions import MatchLevel
from pricing.domain.ruleset import ItemClassification, Rule

RAVEN = ItemClassification(type_id=638, group_id=27, category_id=6)


def make_rule(**kwargs):
    defaults = {
        "label": "test",
        "percent": Decimal("80.00"),
        "category_ids": frozenset(),
        "group_ids": frozenset(),
        "type_ids": frozenset(),
    }
    return Rule(**{**defaults, **kwargs})


def test_type_match_beats_group_and_category():
    rule = make_rule(
        category_ids=frozenset({6}),
        group_ids=frozenset({27}),
        type_ids=frozenset({638}),
    )
    assert rule.match_level(RAVEN) is MatchLevel.TYPE


def test_group_match_when_no_type_target():
    rule = make_rule(category_ids=frozenset({6}), group_ids=frozenset({27}))
    assert rule.match_level(RAVEN) is MatchLevel.GROUP


def test_category_match_when_only_category_targeted():
    rule = make_rule(category_ids=frozenset({6}))
    assert rule.match_level(RAVEN) is MatchLevel.CATEGORY


def test_no_match_returns_none():
    rule = make_rule(category_ids=frozenset({4}))
    assert rule.match_level(RAVEN) is None


def test_rule_without_window_is_always_active():
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    assert make_rule().is_active(now) is True


def test_rule_window_bounds_are_inclusive():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 31, tzinfo=timezone.utc)
    rule = make_rule(valid_from=start, valid_to=end)

    assert rule.is_active(start) is True
    assert rule.is_active(end) is True
    assert rule.is_active(datetime(2026, 7, 31, tzinfo=timezone.utc)) is False
    assert rule.is_active(datetime(2026, 9, 1, tzinfo=timezone.utc)) is False
