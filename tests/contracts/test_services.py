"""Orchestration: refresh, fetch, match, verify.

The gateway and SSO client are injected, so these tests exercise the real
sequencing and the real database without touching the network.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from django.test.utils import override_settings
from django.utils import timezone

from buyback.models import Quote, QuoteItem
from contracts.domain.contract import ContractItemLine, ContractSnapshot
from contracts.domain.gateway import ContractSourceError
from contracts.domain.verdict import Advisory, Problem
from contracts.infrastructure.crypto import TokenCipher, TokenCipherError
from contracts.infrastructure.sso import TokenPair, TokenRejected
from contracts.models import EsiCharacter
from contracts.services import NotLinkedError, run_check

CHARACTER_ID = 1111
SELLER_ID = 2222
KEY = Fernet.generate_key().decode()


class FakeSso:
    """Rotates the refresh token on every call, like the real thing may."""

    def __init__(self, *, fail_with=None):
        self.calls = []
        self._fail_with = fail_with

    def refresh(self, refresh_token):
        self.calls.append(refresh_token)
        if self._fail_with:
            raise self._fail_with
        return TokenPair(access_token="access-token", refresh_token="rotated-token")


class FakeGateway:
    def __init__(self, contracts=(), items=None, names=None):
        self._contracts = contracts
        self._items = items or {}
        self._names = names or {}
        self.item_fetches = []

    def fetch_contracts(self, *, character_id, access_token):
        return self._contracts

    def fetch_items(self, *, character_id, contract_id, access_token):
        self.item_fetches.append(contract_id)
        return self._items.get(contract_id, ())

    def resolve_names(self, ids):
        return self._names


def make_contract(**overrides):
    defaults = {
        "contract_id": 7001,
        "title": "TESTQUOTE",
        "contract_type": "item_exchange",
        "status": "outstanding",
        "price": Decimal("1000.00"),
        "issuer_id": SELLER_ID,
        "assignee_id": CHARACTER_ID,
        "date_issued": timezone.now(),
    }
    return ContractSnapshot(**{**defaults, **overrides})


@pytest.fixture
def linked(db):
    return EsiCharacter.objects.create(
        character_id=CHARACTER_ID,
        character_name="Operator",
        refresh_token_ciphertext=TokenCipher(KEY).encrypt("original-token"),
    )


@pytest.fixture
def quote(db):
    record = Quote.objects.create(
        code="TESTQUOTE", total_value=Decimal("1000.00"), contract_days=3
    )
    QuoteItem.objects.create(
        quote=record,
        type_id=34,
        type_name="Tritanium",
        quantity=1000,
        unit_price=Decimal("1.00"),
        percent_applied=Decimal("100.00"),
        price_source_kind="CATEGORY_DEFAULT",
        line_total=Decimal("1000.00"),
    )
    return record


def matching_items():
    return (
        ContractItemLine(type_id=34, quantity=1000, is_included=True, is_singleton=False),
    )


def check(gateway, sso=None):
    with override_settings(ESI_TOKEN_KEY=KEY):
        return run_check(gateway=gateway, sso=sso or FakeSso(), cipher=TokenCipher(KEY))


@pytest.mark.django_db
def test_a_check_without_a_linked_character_raises():
    with pytest.raises(NotLinkedError):
        check(FakeGateway())


@pytest.mark.django_db
def test_a_check_with_a_cleared_token_raises(linked):
    linked.disconnect("previously rejected")

    with pytest.raises(NotLinkedError):
        check(FakeGateway())


@pytest.mark.django_db
def test_the_rotated_refresh_token_replaces_the_stored_one(linked, quote):
    """The single most important behaviour here.

    SSO may have already invalidated the token we submitted, so failing to
    persist the replacement leaves the link permanently dead — and it would
    look fine until the first access token expired.
    """
    sso = FakeSso()

    check(FakeGateway(), sso)

    assert sso.calls == ["original-token"]
    stored = TokenCipher(KEY).decrypt(EsiCharacter.current().refresh_token_ciphertext)
    assert stored == "rotated-token"


@pytest.mark.django_db
def test_the_rotated_token_is_persisted_even_when_the_fetch_then_fails(linked):
    """The write must happen before the contract fetch, not after it."""

    class FailingGateway(FakeGateway):
        def fetch_contracts(self, *, character_id, access_token):
            raise ContractSourceError("ESI is down")

    with pytest.raises(ContractSourceError):
        check(FailingGateway())

    stored = TokenCipher(KEY).decrypt(EsiCharacter.current().refresh_token_ciphertext)
    assert stored == "rotated-token"


@pytest.mark.django_db
def test_a_rejected_refresh_token_disconnects_the_character(linked):
    sso = FakeSso(fail_with=TokenRejected("SSO rejected the credential."))

    with pytest.raises(TokenRejected):
        check(FakeGateway(), sso)

    reloaded = EsiCharacter.current()
    assert reloaded.is_connected is False
    assert "rejected" in reloaded.last_error.lower()


@pytest.mark.django_db
def test_an_undecryptable_token_disconnects_the_character(linked):
    """ESI_TOKEN_KEY was rotated or lost. Recovery is a re-link, not a crash."""
    other_key = Fernet.generate_key().decode()

    with pytest.raises(TokenCipherError):
        with override_settings(ESI_TOKEN_KEY=other_key):
            run_check(
                gateway=FakeGateway(), sso=FakeSso(), cipher=TokenCipher(other_key)
            )

    assert EsiCharacter.current().is_connected is False


@pytest.mark.django_db
def test_a_matching_contract_comes_back_acceptable(linked, quote):
    gateway = FakeGateway(
        contracts=(make_contract(),),
        items={7001: matching_items()},
        names={SELLER_ID: "Seller One"},
    )

    result = check(gateway)

    assert len(result.verdicts) == 1
    assert result.verdicts[0].is_acceptable
    assert result.ready_count == 1
    assert result.attention_count == 0
    assert result.names[SELLER_ID] == "Seller One"


@pytest.mark.django_db
def test_contracts_the_operator_issued_are_ignored(linked, quote):
    """Otherwise the operator's own outgoing contracts clutter the page."""
    gateway = FakeGateway(contracts=(make_contract(issuer_id=CHARACTER_ID),))

    assert check(gateway).verdicts == ()


@pytest.mark.django_db
def test_contracts_that_are_not_outstanding_are_ignored(linked, quote):
    gateway = FakeGateway(contracts=(make_contract(status="finished"),))

    assert check(gateway).verdicts == ()


@pytest.mark.django_db
def test_items_are_only_fetched_for_contracts_that_match_a_quote(linked, quote):
    """A pile of unrelated contracts must not cost one request each."""
    gateway = FakeGateway(
        contracts=(
            make_contract(contract_id=7001, title="TESTQUOTE"),
            make_contract(contract_id=7002, title="unrelated"),
            make_contract(contract_id=7003, title=""),
        ),
        items={7001: matching_items()},
    )

    check(gateway)

    assert gateway.item_fetches == [7001]


@pytest.mark.django_db
def test_an_unparseable_quote_line_does_not_block_a_match(linked, quote):
    """QuoteItem.type_id is null for a line Janice could not price."""
    QuoteItem.objects.create(
        quote=quote,
        type_id=None,
        type_name="gibberish",
        quantity=1,
        unit_price=Decimal("0.00"),
        percent_applied=Decimal("0.00"),
        price_source_kind="BLACKLIST",
        line_total=Decimal("0.00"),
        is_flagged=True,
    )
    gateway = FakeGateway(contracts=(make_contract(),), items={7001: matching_items()})

    assert check(gateway).verdicts[0].is_acceptable


@pytest.mark.django_db
def test_a_stale_quote_is_flagged_from_the_frozen_window(linked, quote):
    Quote.objects.filter(pk=quote.pk).update(
        created_at=timezone.now() - timedelta(days=10)
    )
    gateway = FakeGateway(contracts=(make_contract(),), items={7001: matching_items()})

    verdict = check(gateway).verdicts[0]

    assert Advisory.QUOTE_STALE in verdict.advisories
    assert verdict.is_acceptable


@pytest.mark.django_db
def test_an_overpriced_contract_is_a_problem(linked, quote):
    """The seller is asking more than they were quoted."""
    gateway = FakeGateway(
        contracts=(make_contract(price=Decimal("2000.00")),),
        items={7001: matching_items()},
    )

    verdict = check(gateway).verdicts[0]

    assert Problem.PRICE_ABOVE_QUOTE in verdict.problems
    assert not verdict.is_acceptable


@pytest.mark.django_db
def test_a_successful_check_records_when_it_ran_and_clears_the_error(linked, quote):
    linked.last_error = "something old"
    linked.save()
    gateway = FakeGateway(contracts=(make_contract(),), items={7001: matching_items()})

    result = check(gateway)

    reloaded = EsiCharacter.current()
    assert reloaded.last_checked_at is not None
    assert reloaded.last_error == ""
    assert result.checked_at == reloaded.last_checked_at
