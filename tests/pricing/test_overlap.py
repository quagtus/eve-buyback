from datetime import datetime, timezone
from decimal import Decimal

from pricing.domain.overlap import find_conflicts, windows_overlap
from pricing.domain.ruleset import Rule

AUG = datetime(2026, 8, 1, tzinfo=timezone.utc)
AUG_END = datetime(2026, 8, 31, tzinfo=timezone.utc)
SEP = datetime(2026, 9, 1, tzinfo=timezone.utc)
SEP_END = datetime(2026, 9, 30, tzinfo=timezone.utc)


def rule(label, percent="80.00", **targets):
    return Rule(label=label, percent=Decimal(percent), **targets)


def test_same_group_target_conflicts():
    a = rule("A", group_ids=frozenset({27}))
    b = rule("B", group_ids=frozenset({27}))

    assert find_conflicts(a, [b]) == ["B"]


def test_same_entity_at_different_levels_does_not_conflict():
    """Ship 80% + Battleship 70% must coexist; that is the whole point."""
    a = rule("Ships", category_ids=frozenset({6}))
    b = rule("Battleships", group_ids=frozenset({27}))

    assert find_conflicts(a, [b]) == []


def test_disjoint_targets_do_not_conflict():
    a = rule("A", type_ids=frozenset({638}))
    b = rule("B", type_ids=frozenset({642}))

    assert find_conflicts(a, [b]) == []


def test_partial_overlap_still_conflicts():
    a = rule("A", category_ids=frozenset({6, 4}))
    b = rule("B", category_ids=frozenset({4}))

    assert find_conflicts(a, [b]) == ["B"]


def test_sales_with_disjoint_windows_do_not_conflict():
    a = rule("Aug", group_ids=frozenset({27}), valid_from=AUG, valid_to=AUG_END)
    b = rule("Sep", group_ids=frozenset({27}), valid_from=SEP, valid_to=SEP_END)

    assert find_conflicts(a, [b]) == []


def test_sales_with_overlapping_windows_conflict():
    a = rule("Aug", group_ids=frozenset({27}), valid_from=AUG, valid_to=SEP)
    b = rule("Sep", group_ids=frozenset({27}), valid_from=AUG_END, valid_to=SEP_END)

    assert find_conflicts(a, [b]) == ["Sep"]


def test_open_ended_windows_overlap_everything():
    assert windows_overlap(None, None, AUG, AUG_END) is True
    assert windows_overlap(AUG, None, SEP, SEP_END) is True
    assert windows_overlap(None, AUG, SEP, SEP_END) is False


def test_touching_endpoints_conflict_closed_intervals():
    """Deliberate closed-interval choice (see module docstring): a sale that
    ends exactly when the next one begins still touches, so the two DO
    conflict. Locks this in so a future switch to half-open intervals fails
    loudly instead of silently changing which sale applies."""
    assert windows_overlap(AUG, AUG_END, AUG_END, SEP_END) is True
