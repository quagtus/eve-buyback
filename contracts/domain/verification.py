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

    return ContractVerdict(
        contract=contract,
        quote_code=quote.code,
        problems=tuple(problems),
        advisories=tuple(advisories),
        price_delta=price_delta,
    )
