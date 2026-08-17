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
from pricing.domain.reprocessing import (
    MaterialValuation,
    MaterialYield,
    ReprocessingInput,
    value_by_reprocessing,
)
from pricing.domain.resolution import resolve_price, resolve_reprocessing
from pricing.domain.ruleset import ItemClassification, RuleSet

__all__ = ["FlagReason", "Quote", "QuoteLine", "build_quote"]

ZERO_ISK = Decimal("0.00")

# Mirrors QuoteItem.type_name's column width (CharField(max_length=255)).
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
    # Reprocessed lines only. Defaulted so every existing construction site and
    # every caller that prices nothing by reprocessing is unaffected.
    materials: tuple[MaterialValuation, ...] = ()
    yield_rate_applied: Decimal | None = None
    portion_size_applied: int | None = None


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
    *,
    material_yields: Mapping[int, tuple[MaterialYield, ...]] | None = None,
    portion_sizes: Mapping[int, int] | None = None,
    material_prices: Mapping[int, Decimal] | None = None,
    material_names: Mapping[int, str] | None = None,
) -> Quote:
    """Price every appraised item.

    The reprocessing arguments are optional and default to empty, so a caller
    that prices nothing by reprocessing is unaffected.
    """
    material_yields = material_yields or {}
    portion_sizes = portion_sizes or {}
    material_prices = material_prices or {}
    material_names = material_names or {}
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

        reprocessing = resolve_reprocessing(classification, ruleset)
        if reprocessing is not None:
            lines.append(
                _reprocessed_line(
                    item=item,
                    rule=reprocessing,
                    ruleset=ruleset,
                    classifications=classifications,
                    now=now,
                    outputs=material_yields.get(item.type_id, ()),
                    portion_size=portion_sizes.get(item.type_id, 1),
                    material_prices=material_prices,
                    material_names=material_names,
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


def _reprocessed_line(
    *,
    item,
    rule,
    ruleset: RuleSet,
    classifications: Mapping[int, ItemClassification],
    now: datetime,
    outputs: tuple[MaterialYield, ...],
    portion_size: int,
    material_prices: Mapping[int, Decimal],
    material_names: Mapping[int, str],
) -> QuoteLine:
    """One quote line valued from reprocessing outputs.

    Each output is resolved through the ordinary tiers, so a Tritanium type rule
    or a Material category default applies exactly as it would to a pasted
    mineral. The ore's own unit price is recorded for display but never used in
    the total.
    """
    decisions = {
        output.type_id: resolve_price(classifications[output.type_id], ruleset, now)
        for output in outputs
        if output.type_id in classifications
    }

    valuation = value_by_reprocessing(
        ReprocessingInput(
            type_id=item.type_id,
            quantity=item.quantity,
            portion_size=portion_size,
            yield_rate=rule.yield_rate,
            outputs=outputs,
        ),
        market_prices=material_prices,
        decisions=decisions,
        material_names=material_names,
    )

    return QuoteLine(
        type_id=item.type_id,
        type_name=item.name[:MAX_TYPE_NAME_LENGTH],
        quantity=item.quantity,
        unit_price=item.unit_price,
        percent_applied=Decimal("0"),
        price_source_kind=PriceSourceKind.REPROCESSED.value,
        price_source_label=rule.label,
        line_total=valuation.total,
        is_flagged=valuation.is_flagged,
        flag_reason=valuation.flag_reason,
        materials=valuation.materials,
        yield_rate_applied=rule.yield_rate,
        portion_size_applied=portion_size,
    )
