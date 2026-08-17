"""Compare a contract to the quote it claims to fulfil.

Pure functions over the domain value objects: no ORM, no network, no clock.
"""

from dataclasses import replace

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

    # These hold whether or not the contract corresponds to a quote, so they run
    # before the early return — a courier contract from a stranger should still
    # say it is the wrong type.
    if contract.contract_type != ITEM_EXCHANGE:
        problems.append(Problem.WRONG_CONTRACT_TYPE)
    if contract.assignee_id != character_id:
        problems.append(Problem.ASSIGNED_ELSEWHERE)

    if quote is None:
        problems.append(Problem.NO_MATCHING_QUOTE)
        return ContractVerdict(
            contract=contract,
            quote_code=None,
            problems=tuple(dict.fromkeys(problems)),
            advisories=tuple(dict.fromkeys(advisories)),
        )

    price_delta = contract.price - quote.total_value
    if price_delta > 0:
        problems.append(Problem.PRICE_ABOVE_QUOTE)
    elif price_delta < 0:
        advisories.append(Advisory.PRICE_BELOW_QUOTE)

    if contract.date_issued > quote.offer_expires_at:
        advisories.append(Advisory.QUOTE_STALE)

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


def verify_all(
    contracts: tuple[ContractSnapshot, ...],
    quotes_by_code: dict[str, QuoteSnapshot],
    items_by_contract_id: dict[int, tuple[ContractItemLine, ...]],
    *,
    character_id: int,
) -> tuple[ContractVerdict, ...]:
    """Verify every contract, then apply the checks that need the whole set.

    Duplicate detection cannot live in verify(): whether a code is used twice is
    a property of the batch, not of one contract.
    """
    code_counts: dict[str, int] = {}
    for contract in contracts:
        code = contract.quote_code
        if code in quotes_by_code:
            code_counts[code] = code_counts.get(code, 0) + 1

    verdicts = []
    for contract in contracts:
        verdict = verify(
            contract,
            quotes_by_code.get(contract.quote_code),
            items_by_contract_id.get(contract.contract_id, ()),
            character_id=character_id,
        )
        if code_counts.get(contract.quote_code, 0) > 1:
            verdict = replace(
                verdict,
                problems=tuple(
                    dict.fromkeys((*verdict.problems, Problem.DUPLICATE_QUOTE_CODE))
                ),
            )
        verdicts.append(verdict)

    # Actionable contracts first, then newest, so the operator's next action is
    # always at the top of the page.
    verdicts.sort(
        key=lambda v: (not v.is_acceptable, -v.contract.date_issued.timestamp())
    )
    return tuple(verdicts)
