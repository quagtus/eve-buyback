"""The match truth table. No database, no network, no clock.

Every comparison is between values carried on the snapshots, including staleness,
which uses the quote's own frozen window rather than "now".
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from contracts.domain.contract import (
    ContractItemLine,
    ContractSnapshot,
    QuoteLine,
    QuoteSnapshot,
)
from contracts.domain.verdict import Advisory, ItemDiff, Problem
from contracts.domain.verification import verify, verify_all

OPERATOR_ID = 1111
SELLER_ID = 2222
ISSUED = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def make_contract(**overrides):
    defaults = {
        "contract_id": 7001,
        "title": "4ovArs",
        "contract_type": "item_exchange",
        "status": "outstanding",
        "price": Decimal("1000.00"),
        "issuer_id": SELLER_ID,
        "assignee_id": OPERATOR_ID,
        "date_issued": ISSUED,
    }
    return ContractSnapshot(**{**defaults, **overrides})


def make_quote(**overrides):
    defaults = {
        "code": "4ovArs",
        "total_value": Decimal("1000.00"),
        # Issued one day into a three-day window, so the default case is fresh.
        "created_at": ISSUED - timedelta(days=1),
        "contract_days": 3,
        "lines": (QuoteLine(type_id=34, quantity=1000),),
    }
    return QuoteSnapshot(**{**defaults, **overrides})


def make_items(*lines):
    """Contract contents that satisfy make_quote() unless overridden."""
    return lines or (
        ContractItemLine(type_id=34, quantity=1000, is_included=True, is_singleton=False),
    )


def run(contract=None, quote=None, items=None):
    return verify(
        contract or make_contract(),
        quote if quote is not None else make_quote(),
        items if items is not None else make_items(),
        character_id=OPERATOR_ID,
    )


def test_an_exact_match_is_acceptable():
    verdict = run()

    assert verdict.is_acceptable
    assert verdict.problems == ()
    assert verdict.advisories == ()
    assert verdict.price_delta == Decimal("0.00")
    assert verdict.quote_code == "4ovArs"


def test_a_price_below_the_quote_is_acceptable_with_an_advisory():
    """Asking for less than quoted is strictly in the operator's favour."""
    verdict = run(contract=make_contract(price=Decimal("999.00")))

    assert verdict.is_acceptable
    assert verdict.advisories == (Advisory.PRICE_BELOW_QUOTE,)
    assert verdict.price_delta == Decimal("-1.00")


def test_a_price_above_the_quote_is_a_problem():
    verdict = run(contract=make_contract(price=Decimal("1000.01")))

    assert not verdict.is_acceptable
    assert Problem.PRICE_ABOVE_QUOTE in verdict.problems
    assert verdict.price_delta == Decimal("0.01")


def test_the_delta_is_exact_at_a_scale_that_would_break_a_float():
    """Quote totals are Decimal all the way through for this reason.

    99999999999999.99 through a binary float comes back as ...98.
    """
    verdict = run(
        contract=make_contract(price=Decimal("99999999999999.99")),
        quote=make_quote(total_value=Decimal("99999999999999.99")),
    )

    assert verdict.price_delta == Decimal("0.00")
    assert verdict.is_acceptable


def test_a_missing_item_is_a_problem_with_a_diff():
    verdict = run(items=())

    assert Problem.ITEM_MISSING in verdict.problems
    assert verdict.item_diffs == (
        ItemDiff(type_id=34, quote_quantity=1000, contract_quantity=0),
    )


def test_an_extra_item_is_a_problem():
    verdict = run(
        items=(
            ContractItemLine(type_id=34, quantity=1000, is_included=True, is_singleton=False),
            ContractItemLine(type_id=638, quantity=1, is_included=True, is_singleton=False),
        )
    )

    assert Problem.ITEM_EXTRA in verdict.problems
    assert ItemDiff(type_id=638, quote_quantity=0, contract_quantity=1) in verdict.item_diffs


def test_a_quantity_mismatch_is_a_problem():
    verdict = run(
        items=(
            ContractItemLine(type_id=34, quantity=999, is_included=True, is_singleton=False),
        )
    )

    assert Problem.QUANTITY_MISMATCH in verdict.problems
    assert verdict.item_diffs == (
        ItemDiff(type_id=34, quote_quantity=1000, contract_quantity=999),
    )


def test_the_same_type_in_several_stacks_is_summed():
    """A contract can carry one type as several stacks; the quote has one line."""
    verdict = run(
        items=(
            ContractItemLine(type_id=34, quantity=600, is_included=True, is_singleton=False),
            ContractItemLine(type_id=34, quantity=400, is_included=True, is_singleton=False),
        )
    )

    assert verdict.is_acceptable
    assert verdict.item_diffs == ()


def test_a_requested_item_is_a_problem_and_does_not_count_as_offered():
    """is_included false means the seller is demanding that item from us.

    It must not be able to satisfy a quote line, or a contract that hands over
    nothing and asks for 1000 Tritanium would read as an exact match.
    """
    verdict = run(
        items=(
            ContractItemLine(type_id=34, quantity=1000, is_included=False, is_singleton=False),
        )
    )

    assert not verdict.is_acceptable
    assert Problem.ITEMS_REQUESTED in verdict.problems
    assert Problem.ITEM_MISSING in verdict.problems


def test_assembled_items_are_an_advisory_not_a_problem():
    """Janice priced the item packaged; an assembled one may be damaged or fitted."""
    verdict = run(
        quote=make_quote(lines=(QuoteLine(type_id=638, quantity=1),)),
        items=(
            ContractItemLine(type_id=638, quantity=1, is_included=True, is_singleton=True),
        ),
    )

    assert verdict.is_acceptable
    assert Advisory.ASSEMBLED_ITEMS in verdict.advisories


def test_unparseable_quote_lines_are_ignored():
    """QuoteItem.type_id is null for a paste line Janice could not price.

    Those lines are always flagged and zero-valued, so they were never part of
    the offer. Requiring them would make every quote containing a typo
    impossible to fulfil.
    """
    verdict = run(
        quote=make_quote(
            lines=(
                QuoteLine(type_id=34, quantity=1000),
                QuoteLine(type_id=None, quantity=1),
            )
        )
    )

    assert verdict.is_acceptable
    assert verdict.item_diffs == ()


def test_each_item_problem_is_reported_once_however_many_types_hit_it():
    """Three missing types are one ITEM_MISSING problem and three diffs."""
    verdict = run(
        quote=make_quote(
            lines=(
                QuoteLine(type_id=34, quantity=1),
                QuoteLine(type_id=35, quantity=1),
                QuoteLine(type_id=36, quantity=1),
            )
        ),
        items=(),
    )

    assert verdict.problems.count(Problem.ITEM_MISSING) == 1
    assert len(verdict.item_diffs) == 3


def test_a_contract_with_no_matching_quote_is_a_problem():
    verdict = verify(
        make_contract(title="not-a-quote-code"),
        None,
        (),
        character_id=OPERATOR_ID,
    )

    assert verdict.problems == (Problem.NO_MATCHING_QUOTE,)
    assert verdict.quote_code is None
    assert verdict.price_delta is None


def test_contract_level_problems_are_reported_even_without_a_quote():
    """A courier contract from a stranger must still say it is the wrong type."""
    verdict = verify(
        make_contract(title="not-a-quote-code", contract_type="courier"),
        None,
        (),
        character_id=OPERATOR_ID,
    )

    assert Problem.WRONG_CONTRACT_TYPE in verdict.problems
    assert Problem.NO_MATCHING_QUOTE in verdict.problems


def test_a_non_item_exchange_contract_is_a_problem():
    verdict = run(contract=make_contract(contract_type="auction"))

    assert Problem.WRONG_CONTRACT_TYPE in verdict.problems


def test_a_contract_assigned_to_someone_else_is_a_problem():
    """In practice this means assigned to the operator's corporation."""
    verdict = run(contract=make_contract(assignee_id=9999))

    assert Problem.ASSIGNED_ELSEWHERE in verdict.problems


def test_a_contract_issued_after_the_quote_window_is_stale():
    verdict = run(
        quote=make_quote(created_at=ISSUED - timedelta(days=4), contract_days=3)
    )

    assert verdict.is_acceptable
    assert Advisory.QUOTE_STALE in verdict.advisories


def test_a_contract_issued_inside_the_quote_window_is_not_stale():
    verdict = run(
        quote=make_quote(created_at=ISSUED - timedelta(days=2), contract_days=3)
    )

    assert Advisory.QUOTE_STALE not in verdict.advisories


def test_verify_all_flags_two_contracts_citing_the_same_quote_code():
    """A seller could contract the same quote twice and be paid twice."""
    first = make_contract(contract_id=1)
    second = make_contract(contract_id=2)
    quote = make_quote()

    verdicts = verify_all(
        (first, second),
        {quote.code: quote},
        {1: make_items(), 2: make_items()},
        character_id=OPERATOR_ID,
    )

    assert len(verdicts) == 2
    for verdict in verdicts:
        assert Problem.DUPLICATE_QUOTE_CODE in verdict.problems
        assert not verdict.is_acceptable


def test_verify_all_does_not_flag_unmatched_titles_as_duplicates():
    """Two unrelated contracts with blank descriptions are not duplicates."""
    verdicts = verify_all(
        (make_contract(contract_id=1, title=""), make_contract(contract_id=2, title="")),
        {},
        {},
        character_id=OPERATOR_ID,
    )

    for verdict in verdicts:
        assert Problem.DUPLICATE_QUOTE_CODE not in verdict.problems
        assert Problem.NO_MATCHING_QUOTE in verdict.problems


def test_verify_all_puts_acceptable_contracts_first_then_newest():
    # Distinct codes, or the duplicate check would correctly reject both and
    # there would be nothing acceptable left to sort.
    old_quote = make_quote(code="OLDER1")
    new_quote = make_quote(code="NEWER1")
    ready_old = make_contract(
        contract_id=1, title="OLDER1", date_issued=ISSUED - timedelta(days=2)
    )
    ready_new = make_contract(contract_id=2, title="NEWER1", date_issued=ISSUED)
    broken = make_contract(contract_id=3, title="unknown", date_issued=ISSUED)

    verdicts = verify_all(
        (broken, ready_old, ready_new),
        {old_quote.code: old_quote, new_quote.code: new_quote},
        {1: make_items(), 2: make_items()},
        character_id=OPERATOR_ID,
    )

    assert [v.is_acceptable for v in verdicts] == [True, True, False]
    assert [v.contract.contract_id for v in verdicts] == [2, 1, 3]


def test_verify_all_matches_a_title_with_surrounding_whitespace():
    quote = make_quote()
    contract = make_contract(contract_id=1, title=" 4ovArs ")

    verdicts = verify_all(
        (contract,), {quote.code: quote}, {1: make_items()}, character_id=OPERATOR_ID
    )

    assert verdicts[0].is_acceptable
    assert verdicts[0].quote_code == "4ovArs"
