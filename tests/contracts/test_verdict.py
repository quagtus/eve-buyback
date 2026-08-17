"""A verdict's two severities are the whole point of the feature.

Problems block green; advisories annotate a green row. Collapsing them into one
list would make green so rare it would stop meaning anything — a seller who
rounded the price down in the operator's favour must not read the same as one who
swapped the items.
"""

from datetime import datetime, timezone
from decimal import Decimal

from contracts.domain.contract import ContractSnapshot
from contracts.domain.verdict import Advisory, ContractVerdict, Problem

CONTRACT = ContractSnapshot(
    contract_id=1,
    title="4ovArs",
    contract_type="item_exchange",
    status="outstanding",
    price=Decimal("100.00"),
    issuer_id=2222,
    assignee_id=1111,
    date_issued=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
)


def test_a_verdict_with_no_problems_is_acceptable():
    verdict = ContractVerdict(contract=CONTRACT, quote_code="4ovArs")

    assert verdict.is_acceptable is True


def test_advisories_alone_do_not_block_acceptance():
    verdict = ContractVerdict(
        contract=CONTRACT,
        quote_code="4ovArs",
        advisories=(Advisory.PRICE_BELOW_QUOTE,),
    )

    assert verdict.is_acceptable is True


def test_any_problem_blocks_acceptance():
    verdict = ContractVerdict(
        contract=CONTRACT,
        quote_code="4ovArs",
        problems=(Problem.PRICE_ABOVE_QUOTE,),
    )

    assert verdict.is_acceptable is False


def test_problem_and_advisory_keys_do_not_overlap():
    """A key appearing in both would be ambiguous at render time."""
    assert not (set(Problem) & set(Advisory))


def test_keys_are_their_own_values():
    """Templates and tests both compare against the plain string."""
    assert Problem.ITEM_MISSING == "ITEM_MISSING"
    assert Advisory.QUOTE_STALE == "QUOTE_STALE"


def test_contract_quote_code_is_the_stripped_title():
    """EVE's contract Description arrives as ESI's `title`, often with whitespace."""
    padded = ContractSnapshot(
        contract_id=2,
        title="  4ovArs \n",
        contract_type="item_exchange",
        status="outstanding",
        price=Decimal("1"),
        issuer_id=2222,
        assignee_id=1111,
        date_issued=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )

    assert padded.quote_code == "4ovArs"
