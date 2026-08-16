"""Detect rules that would make price resolution ambiguous.

Two rules conflict when they target the same entity at the same level. Rules
targeting the same entity at *different* levels are fine and expected —
Ship 80% plus Battleship 70% is the intended way to express nested pricing.

Sales additionally only conflict when their validity windows intersect, so
sequential sales on the same target are legal.
"""

from datetime import datetime
from typing import Iterable

from pricing.domain.ruleset import Rule


def windows_overlap(
    a_from: datetime | None,
    a_to: datetime | None,
    b_from: datetime | None,
    b_to: datetime | None,
) -> bool:
    """Closed-interval intersection where None means unbounded."""
    if a_to is not None and b_from is not None and a_to < b_from:
        return False
    if b_to is not None and a_from is not None and b_to < a_from:
        return False
    return True


def _shares_target(a: Rule, b: Rule) -> bool:
    return bool(
        (a.category_ids & b.category_ids)
        or (a.group_ids & b.group_ids)
        or (a.type_ids & b.type_ids)
    )


def find_conflicts(candidate: Rule, existing: Iterable[Rule]) -> list[str]:
    """Return the labels of rules that conflict with `candidate`."""
    conflicts = []
    for other in existing:
        if not _shares_target(candidate, other):
            continue
        if not windows_overlap(
            candidate.valid_from, candidate.valid_to, other.valid_from, other.valid_to
        ):
            continue
        conflicts.append(other.label)
    return conflicts
