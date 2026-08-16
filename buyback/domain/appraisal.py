"""Framework-free representation of an appraisal, independent of Janice."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AppraisalItem:
    type_id: int
    name: str
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class AppraisalResult:
    code: str
    items: tuple[AppraisalItem, ...]
    failures: tuple[str, ...]

    @property
    def has_items(self) -> bool:
        return bool(self.items)
