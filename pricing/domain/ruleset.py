"""Frozen, framework-free representation of the admin's configured rules."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from pricing.domain.decisions import MatchLevel


@dataclass(frozen=True)
class ItemClassification:
    """Where a single EVE item sits in the category hierarchy."""

    type_id: int
    group_id: int
    category_id: int


def match_level(
    item: ItemClassification, *, category_ids, group_ids, type_ids
) -> MatchLevel | None:
    """How specifically these target sets match `item`, or None.

    Shared by Rule and ReprocessingRule so the two cannot drift apart. Both are
    walked by the same `_best_match` in resolution.py.
    """
    if item.type_id in type_ids:
        return MatchLevel.TYPE
    if item.group_id in group_ids:
        return MatchLevel.GROUP
    if item.category_id in category_ids:
        return MatchLevel.CATEGORY
    return None


@dataclass(frozen=True)
class Rule:
    """A percentage rule targeting any mix of categories, groups and types.

    There is deliberately no `scope` field: specificity is derived from which
    target set matched, so there is no redundant state to keep in sync.
    A rule with no time window is always active.
    """

    label: str
    percent: Decimal
    category_ids: frozenset[int] = field(default_factory=frozenset)
    group_ids: frozenset[int] = field(default_factory=frozenset)
    type_ids: frozenset[int] = field(default_factory=frozenset)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def match_level(self, item: ItemClassification) -> MatchLevel | None:
        return match_level(
            item,
            category_ids=self.category_ids,
            group_ids=self.group_ids,
            type_ids=self.type_ids,
        )

    @property
    def tie_break_value(self) -> Decimal:
        """Value `_best_match` compares when two rules match at the same level."""
        return self.percent

    def is_active(self, now: datetime) -> bool:
        """Return whether this rule is active at `now`.

        `now` must be timezone-aware whenever a sale window is configured
        (`valid_from` and/or `valid_to` set) — comparing it against a
        timezone-aware bound otherwise raises `TypeError: can't compare
        offset-naive and offset-aware datetimes`. Callers should pass
        Django's timezone-aware `timezone.now()` helper, not the naive
        `datetime.now()` or `datetime.utcnow()`.
        """
        if self.valid_from is not None and now < self.valid_from:
            return False
        if self.valid_to is not None and now > self.valid_to:
            return False
        return True


@dataclass(frozen=True)
class ReprocessingRule:
    """Marks matched items to be valued from their reprocessing outputs.

    yield_rate is a fraction, not percentage points: Decimal("0.9063") is 90.63%
    recovery. It is deliberately not called `percent`, because the percentages
    elsewhere in this package are points and mixing the two silently divides a
    price by 100.
    """

    label: str
    yield_rate: Decimal
    category_ids: frozenset[int] = field(default_factory=frozenset)
    group_ids: frozenset[int] = field(default_factory=frozenset)
    type_ids: frozenset[int] = field(default_factory=frozenset)

    def match_level(self, item: ItemClassification) -> MatchLevel | None:
        return match_level(
            item,
            category_ids=self.category_ids,
            group_ids=self.group_ids,
            type_ids=self.type_ids,
        )

    @property
    def tie_break_value(self) -> Decimal:
        return self.yield_rate


@dataclass(frozen=True)
class RuleSet:
    """Everything price resolution needs, loaded once per quote."""

    blacklist_category_ids: frozenset[int] = field(default_factory=frozenset)
    blacklist_group_ids: frozenset[int] = field(default_factory=frozenset)
    blacklist_type_ids: frozenset[int] = field(default_factory=frozenset)
    sales: tuple[Rule, ...] = ()
    custom_rules: tuple[Rule, ...] = ()
    reprocessing_rules: tuple[ReprocessingRule, ...] = ()
    category_defaults: Mapping[int, Decimal] = field(default_factory=dict)

    def is_blacklisted(self, item: ItemClassification) -> bool:
        return (
            item.type_id in self.blacklist_type_ids
            or item.group_id in self.blacklist_group_ids
            or item.category_id in self.blacklist_category_ids
        )
