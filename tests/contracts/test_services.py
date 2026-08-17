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
from contracts.infrastructure.sso import (
    CONTRACTS_SCOPE,
    CharacterIdentity,
    TokenPair,
    TokenRejected,
)
from contracts.models import EsiCharacter
from contracts.services import (
    MissingScopeError,
    NotLinkedError,
    link_character,
    run_check,
)

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


class FakeLinkSso:
    """Exchange half of the SSO client, for the link path."""

    def __init__(self):
        self.revoked = []

    def exchange_code(self, code, code_verifier):
        return TokenPair(access_token="access-1", refresh_token="refresh-1")

    def revoke(self, refresh_token):
        self.revoked.append(refresh_token)


class FakeValidator:
    def __init__(self, *, scopes, character_id=CHARACTER_ID, name="Operator"):
        self._identity = CharacterIdentity(
            character_id=character_id, character_name=name, scopes=scopes
        )

    def identity(self, access_token):
        return self._identity


def link(scopes, **kwargs):
    with override_settings(ESI_TOKEN_KEY=KEY):
        return link_character(
            code="the-code",
            code_verifier="the-verifier",
            sso=kwargs.pop("sso", None) or FakeLinkSso(),
            validator=FakeValidator(scopes=scopes, **kwargs),
            cipher=TokenCipher(KEY),
        )


@pytest.mark.django_db
def test_linking_stores_the_character_and_encrypts_the_token():
    character = link((CONTRACTS_SCOPE,))

    assert character.character_id == CHARACTER_ID
    assert character.character_name == "Operator"
    assert character.is_connected
    assert TokenCipher(KEY).decrypt(character.refresh_token_ciphertext) == "refresh-1"
    # The plaintext must not be recoverable from the column itself.
    assert "refresh-1" not in character.refresh_token_ciphertext


@pytest.mark.django_db
def test_linking_without_the_contracts_scope_is_refused_before_storing_anything():
    """A token that cannot read contracts is worse than no token: it would link
    cleanly and then 403 on the first check."""
    with pytest.raises(MissingScopeError) as exc:
        link(("esi-characters.read_contacts.v1",))

    message = str(exc.value)
    assert CONTRACTS_SCOPE in message
    assert "developers.eveonline.com" in message
    assert EsiCharacter.current() is None


@pytest.mark.django_db
def test_linking_with_no_scopes_at_all_says_so():
    with pytest.raises(MissingScopeError) as exc:
        link(())

    assert "no scopes" in str(exc.value)


@pytest.mark.django_db
def test_linking_a_different_character_revokes_the_previous_token():
    """Housekeeping: the replaced credential should not stay live at CCP."""
    link((CONTRACTS_SCOPE,))
    sso = FakeLinkSso()

    link((CONTRACTS_SCOPE,), sso=sso, character_id=9999, name="Someone Else")

    assert sso.revoked == ["refresh-1"]
    assert EsiCharacter.objects.count() == 1
    assert EsiCharacter.current().character_name == "Someone Else"


@pytest.mark.django_db
def test_relinking_the_same_character_does_not_revoke():
    """Reconnecting the same pilot is a refresh, not a replacement."""
    link((CONTRACTS_SCOPE,))
    sso = FakeLinkSso()

    link((CONTRACTS_SCOPE,), sso=sso)

    assert sso.revoked == []
