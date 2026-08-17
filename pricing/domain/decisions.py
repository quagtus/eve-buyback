"""Value objects describing a pricing decision. Pure Python — no Django."""

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum


class PriceSourceKind(StrEnum):
    """Which category of rule set an item's price.

    Values are UPPERCASE because they are persisted to
    QuoteItem.price_source_kind and looked up by the presentation layer.
    They must match the keys the backfill migration writes and the keys the
    template filter reads — lowercase values would make every newly generated
    quote render a blank Source column while backfilled rows looked correct.
    """

    BLACKLIST = "BLACKLIST"
    SALE = "SALE"
    CUSTOM = "CUSTOM"
    CATEGORY_DEFAULT = "CATEGORY_DEFAULT"
    REPROCESSED = "REPROCESSED"
    NONE = "NONE"


class MatchLevel(IntEnum):
    """How specifically a rule matched an item. Higher wins within a tier."""

    CATEGORY = 1
    GROUP = 2
    TYPE = 3


class FlagReason(StrEnum):
    """Why a line was rejected. A stable key — never displayed raw."""

    BLACKLISTED = "BLACKLISTED"
    NO_RULE = "NO_RULE"
    UNRECOGNIZED = "UNRECOGNIZED"
    UNPARSEABLE = "UNPARSEABLE"
    BELOW_PORTION_SIZE = "BELOW_PORTION_SIZE"
    ZERO_YIELD = "ZERO_YIELD"


@dataclass(frozen=True)
class PriceDecision:
    """The outcome of resolving one item against the rule set.

    `percent` is in percentage points: Decimal("80.00") means 80%.

    `source_kind` is a machine key for the *category* of rule that won.
    `rule_name` is the admin-authored name of the winning rule, and is
    empty for system sources. The two are separate because they need
    opposite treatment at render time: the kind is translated, the
    rule name never is — it is the operator's data, not UI text.
    """

    percent: Decimal
    source_kind: PriceSourceKind
    rule_name: str = ""
    flagged: bool = False
    flag_reason: "FlagReason | None" = None
