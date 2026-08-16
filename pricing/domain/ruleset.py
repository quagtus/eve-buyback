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
        if item.type_id in self.type_ids:
            return MatchLevel.TYPE
        if item.group_id in self.group_ids:
            return MatchLevel.GROUP
        if item.category_id in self.category_ids:
            return MatchLevel.CATEGORY
        return None

    def is_active(self, now: datetime) -> bool:
        if self.valid_from is not None and now < self.valid_from:
            return False
        if self.valid_to is not None and now > self.valid_to:
            return False
        return True


@dataclass(frozen=True)
class RuleSet:
    """Everything price resolution needs, loaded once per quote."""

    blacklist_category_ids: frozenset[int] = field(default_factory=frozenset)
    blacklist_group_ids: frozenset[int] = field(default_factory=frozenset)
    blacklist_type_ids: frozenset[int] = field(default_factory=frozenset)
    sales: tuple[Rule, ...] = ()
    custom_rules: tuple[Rule, ...] = ()
    category_defaults: Mapping[int, Decimal] = field(default_factory=dict)

    def is_blacklisted(self, item: ItemClassification) -> bool:
        return (
            item.type_id in self.blacklist_type_ids
            or item.group_id in self.blacklist_group_ids
            or item.category_id in self.blacklist_category_ids
        )
