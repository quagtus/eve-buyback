"""Value objects describing a pricing decision. Pure Python — no Django."""

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum


class PriceSourceKind(StrEnum):
    BLACKLIST = "blacklist"
    SALE = "sale"
    CUSTOM = "custom"
    CATEGORY_DEFAULT = "category_default"
    NONE = "none"


class MatchLevel(IntEnum):
    """How specifically a rule matched an item. Higher wins within a tier."""

    CATEGORY = 1
    GROUP = 2
    TYPE = 3


@dataclass(frozen=True)
class PriceDecision:
    """The outcome of resolving one item against the rule set.

    `percent` is in percentage points: Decimal("80.00") means 80%.
    """

    percent: Decimal
    source_kind: PriceSourceKind
    source_label: str
    flagged: bool = False
    flag_reason: str | None = None
