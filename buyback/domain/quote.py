"""Turn an appraisal plus a rule set into priced, flagged quote lines.

Pure: no ORM, no HTTP, no clock. The caller supplies `now` and the type_id ->
ItemClassification mapping.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from buyback.domain.appraisal import AppraisalResult
from buyback.domain.money import line_total, sum_totals
from pricing.domain.decisions import FlagReason, PriceSourceKind
from pricing.domain.resolution import resolve_price
from pricing.domain.ruleset import ItemClassification, RuleSet

__all__ = ["FlagReason", "Quote", "QuoteLine", "build_quote"]

ZERO_ISK = Decimal("0.00")

# Mirrors SnapshotItem.type_name's column width (CharField(max_length=255)).
# Failure text and item names are upstream/user-echoed data we don't control,
# so they must be truncated before they ever reach persistence.
MAX_TYPE_NAME_LENGTH = 255


@dataclass(frozen=True)
class QuoteLine:
    type_id: int | None
    type_name: str
    quantity: int
    unit_price: Decimal
    percent_applied: Decimal
    price_source_kind: str
    price_source_label: str
    line_total: Decimal
    is_flagged: bool
    flag_reason: FlagReason | None


@dataclass(frozen=True)
class Quote:
    code: str
    lines: tuple[QuoteLine, ...]
    total_value: Decimal


def build_quote(
    appraisal: AppraisalResult,
    ruleset: RuleSet,
    classifications: Mapping[int, ItemClassification],
    now: datetime,
) -> Quote:
    lines: list[QuoteLine] = []

    for item in appraisal.items:
        classification = classifications.get(item.type_id)
        if classification is None:
            lines.append(
                QuoteLine(
                    type_id=item.type_id,
                    type_name=item.name[:MAX_TYPE_NAME_LENGTH],
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    percent_applied=Decimal("0"),
                    price_source_kind=PriceSourceKind.NONE.value,
                    price_source_label="",
                    line_total=ZERO_ISK,
                    is_flagged=True,
                    flag_reason=FlagReason.UNRECOGNIZED,
                )
            )
            continue

        decision = resolve_price(classification, ruleset, now)
        total = (
            ZERO_ISK
            if decision.flagged
            else line_total(item.unit_price, item.quantity, decision.percent)
        )
        lines.append(
            QuoteLine(
                type_id=item.type_id,
                type_name=item.name[:MAX_TYPE_NAME_LENGTH],
                quantity=item.quantity,
                unit_price=item.unit_price,
                percent_applied=decision.percent,
                price_source_kind=decision.source_kind.value,
                price_source_label=decision.rule_name,
                line_total=total,
                is_flagged=decision.flagged,
                flag_reason=decision.flag_reason,
            )
        )

    for failure in appraisal.failures:
        lines.append(
            QuoteLine(
                type_id=None,
                type_name=failure[:MAX_TYPE_NAME_LENGTH],
                quantity=0,
                unit_price=ZERO_ISK,
                percent_applied=Decimal("0"),
                price_source_kind=PriceSourceKind.NONE.value,
                price_source_label="",
                line_total=ZERO_ISK,
                is_flagged=True,
                flag_reason=FlagReason.UNPARSEABLE,
            )
        )

    return Quote(
        code=appraisal.code,
        lines=tuple(lines),
        total_value=sum_totals(line.line_total for line in lines),
    )
