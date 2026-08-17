"""Value an item from what it reprocesses into.

Pure: no ORM, no network, no clock. The caller supplies market prices, one
PriceDecision per output material, and the display names.

Reprocessing chooses the *basis*; resolve_price still chooses the fraction paid.
That is why decisions arrive per material rather than per ore.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Mapping

from pricing.domain.decisions import FlagReason, PriceDecision, PriceSourceKind

ZERO_ISK = Decimal("0.00")
CENTS = Decimal("0.01")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class MaterialYield:
    """One output of a type, per batch of portion_size — never per unit."""

    type_id: int
    quantity_per_batch: int


@dataclass(frozen=True)
class ReprocessingInput:
    type_id: int
    quantity: int
    portion_size: int
    yield_rate: Decimal
    outputs: tuple[MaterialYield, ...]


@dataclass(frozen=True)
class MaterialValuation:
    type_id: int
    type_name: str
    quantity: int
    unit_price: Decimal
    percent_applied: Decimal
    line_total: Decimal
    is_unpriced: bool


@dataclass(frozen=True)
class ReprocessedValuation:
    materials: tuple[MaterialValuation, ...]
    total: Decimal
    batches: int
    remainder: int
    is_flagged: bool = False
    flag_reason: FlagReason | None = None


def _flagged(batches: int, remainder: int, reason: FlagReason) -> ReprocessedValuation:
    return ReprocessedValuation(
        materials=(),
        total=ZERO_ISK,
        batches=batches,
        remainder=remainder,
        is_flagged=True,
        flag_reason=reason,
    )


def value_by_reprocessing(
    spec: ReprocessingInput,
    *,
    market_prices: Mapping[int, Decimal],
    decisions: Mapping[int, PriceDecision],
    material_names: Mapping[int, str],
) -> ReprocessedValuation:
    portion = max(spec.portion_size, 1)
    batches = spec.quantity // portion
    remainder = spec.quantity % portion

    if not spec.outputs:
        return _flagged(batches, remainder, FlagReason.NO_RULE)
    if spec.yield_rate <= 0:
        return _flagged(batches, remainder, FlagReason.ZERO_YIELD)
    if batches == 0:
        return _flagged(batches, remainder, FlagReason.BELOW_PORTION_SIZE)

    materials: list[MaterialValuation] = []
    for output in spec.outputs:
        # Floor once over the whole lot. Flooring each batch instead would zero
        # any material yielding 1 per batch.
        units = int(
            (
                Decimal(output.quantity_per_batch)
                * Decimal(batches)
                * spec.yield_rate
            ).to_integral_value(rounding=ROUND_DOWN)
        )

        price = market_prices.get(output.type_id)
        decision = decisions.get(output.type_id)
        unpriced = (
            price is None
            or decision is None
            or decision.source_kind == PriceSourceKind.NONE
        )

        if unpriced or decision.flagged:
            percent, total = Decimal("0"), ZERO_ISK
        else:
            percent = decision.percent
            total = (Decimal(units) * price * percent / HUNDRED).quantize(CENTS)

        materials.append(
            MaterialValuation(
                type_id=output.type_id,
                type_name=material_names.get(output.type_id, str(output.type_id)),
                quantity=units,
                unit_price=price if price is not None else ZERO_ISK,
                percent_applied=percent,
                line_total=total,
                is_unpriced=unpriced,
            )
        )

    return ReprocessedValuation(
        materials=tuple(materials),
        total=sum((m.line_total for m in materials), ZERO_ISK).quantize(CENTS),
        batches=batches,
        remainder=remainder,
    )
