"""What verification concluded about one contract.

Keys are machine strings resolved to prose in the template, the same split the
rest of the project uses for price_source_kind and flag_reason_code. The admin is
English only, so this is about keeping the domain free of presentation rather
than about translation.

Advisory, not Warning: `Warning` is a builtin exception class and shadowing it in
a module that also raises would be a trap.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from contracts.domain.contract import ContractSnapshot


class Problem(StrEnum):
    """Reasons a contract is not safe to accept as it stands."""

    NO_MATCHING_QUOTE = "NO_MATCHING_QUOTE"
    DUPLICATE_QUOTE_CODE = "DUPLICATE_QUOTE_CODE"
    WRONG_CONTRACT_TYPE = "WRONG_CONTRACT_TYPE"
    ASSIGNED_ELSEWHERE = "ASSIGNED_ELSEWHERE"
    PRICE_ABOVE_QUOTE = "PRICE_ABOVE_QUOTE"
    ITEMS_REQUESTED = "ITEMS_REQUESTED"
    ITEM_MISSING = "ITEM_MISSING"
    ITEM_EXTRA = "ITEM_EXTRA"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"


class Advisory(StrEnum):
    """Acceptable, but the operator should see it."""

    PRICE_BELOW_QUOTE = "PRICE_BELOW_QUOTE"
    ASSEMBLED_ITEMS = "ASSEMBLED_ITEMS"
    QUOTE_STALE = "QUOTE_STALE"


@dataclass(frozen=True)
class ItemDiff:
    """One type where the contract and the quote disagree."""

    type_id: int
    quote_quantity: int
    contract_quantity: int


@dataclass(frozen=True)
class ContractVerdict:
    contract: ContractSnapshot
    quote_code: str | None
    problems: tuple[Problem, ...] = ()
    advisories: tuple[Advisory, ...] = ()
    price_delta: Decimal | None = None
    item_diffs: tuple[ItemDiff, ...] = ()

    @property
    def is_acceptable(self) -> bool:
        return not self.problems
