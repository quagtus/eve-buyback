"""Compare a contract to the quote it claims to fulfil.

Pure functions over the domain value objects: no ORM, no network, no clock.
"""

from contracts.domain.contract import (
    ITEM_EXCHANGE,
    ContractItemLine,
    ContractSnapshot,
    QuoteSnapshot,
)
from contracts.domain.verdict import Advisory, ContractVerdict, ItemDiff, Problem


def _aggregate_contract(lines: tuple[ContractItemLine, ...]) -> dict[int, int]:
    """Sum offered quantities per type. A contract may split one type into stacks."""
    totals: dict[int, int] = {}
    for line in lines:
        totals[line.type_id] = totals.get(line.type_id, 0) + line.quantity
    return totals


def _aggregate_quote(quote: QuoteSnapshot) -> dict[int, int]:
    """Sum quoted quantities per type, skipping unpriceable lines."""
    totals: dict[int, int] = {}
    for line in quote.lines:
        if line.type_id is None:
            continue
        totals[line.type_id] = totals.get(line.type_id, 0) + line.quantity
    return totals


def verify(
    contract: ContractSnapshot,
    quote: QuoteSnapshot | None,
    items: tuple[ContractItemLine, ...],
    *,
    character_id: int,
) -> ContractVerdict:
    problems: list[Problem] = []
    advisories: list[Advisory] = []

    price_delta = contract.price - quote.total_value
    if price_delta > 0:
        problems.append(Problem.PRICE_ABOVE_QUOTE)
    elif price_delta < 0:
        advisories.append(Advisory.PRICE_BELOW_QUOTE)

    requested = [line for line in items if not line.is_included]
    if requested:
        problems.append(Problem.ITEMS_REQUESTED)

    offered = tuple(line for line in items if line.is_included)
    if any(line.is_singleton for line in offered):
        advisories.append(Advisory.ASSEMBLED_ITEMS)

    quoted = _aggregate_quote(quote)
    carried = _aggregate_contract(offered)
    item_diffs: list[ItemDiff] = []
    for type_id in sorted(quoted.keys() | carried.keys()):
        want = quoted.get(type_id, 0)
        have = carried.get(type_id, 0)
        if want == have:
            continue
        if have == 0:
            problems.append(Problem.ITEM_MISSING)
        elif want == 0:
            problems.append(Problem.ITEM_EXTRA)
        else:
            problems.append(Problem.QUANTITY_MISMATCH)
        item_diffs.append(
            ItemDiff(type_id=type_id, quote_quantity=want, contract_quantity=have)
        )

    return ContractVerdict(
        contract=contract,
        quote_code=quote.code,
        # dict.fromkeys deduplicates while preserving order: three missing types
        # are one ITEM_MISSING problem and three diffs.
        problems=tuple(dict.fromkeys(problems)),
        advisories=tuple(dict.fromkeys(advisories)),
        price_delta=price_delta,
        item_diffs=tuple(item_diffs),
    )
