"""ESI adapter.

Schema verified against https://esi.evetech.net/meta/openapi.json:
  GET /characters/{id}/contracts              paginated via the X-Pages header
  GET /characters/{id}/contracts/{cid}/items  not paginated
  POST /universe/names                        unauthenticated, batched
"""

from decimal import Decimal

import pytest
import requests
import responses

from contracts.domain.contract import ContractItemLine
from contracts.domain.gateway import ContractSourceError, ScopeRejected
from contracts.infrastructure.esi import BASE_URL, EsiContractGateway

CHARACTER_ID = 1111
CONTRACTS_URL = f"{BASE_URL}/characters/{CHARACTER_ID}/contracts"
NAMES_URL = f"{BASE_URL}/universe/names"

CONTRACT_ROW = {
    "contract_id": 7001,
    "title": "4ovArs",
    "type": "item_exchange",
    "status": "outstanding",
    "price": 1234567.89,
    "issuer_id": 2222,
    "issuer_corporation_id": 3333,
    "assignee_id": CHARACTER_ID,
    "acceptor_id": 0,
    "for_corporation": False,
    "availability": "personal",
    "date_issued": "2026-08-17T12:00:00Z",
    "date_expired": "2026-08-20T12:00:00Z",
}


def build_gateway():
    return EsiContractGateway(user_agent="eve-buyback tests")


def items_url(contract_id):
    return f"{BASE_URL}/characters/{CHARACTER_ID}/contracts/{contract_id}/items"


@responses.activate
def test_a_contract_row_maps_onto_the_domain_snapshot():
    responses.add(responses.GET, CONTRACTS_URL, json=[CONTRACT_ROW], status=200)

    contract = build_gateway().fetch_contracts(
        character_id=CHARACTER_ID, access_token="token"
    )[0]

    assert contract.contract_id == 7001
    assert contract.quote_code == "4ovArs"
    assert contract.contract_type == "item_exchange"
    assert contract.status == "outstanding"
    assert contract.issuer_id == 2222
    assert contract.assignee_id == CHARACTER_ID
    assert contract.date_issued.year == 2026
    assert contract.date_issued.tzinfo is not None


@responses.activate
def test_the_price_is_a_decimal_not_a_float():
    """A float round-trip loses a cent around 1e14, the same reason the Janice
    adapter parses with parse_float=Decimal.

    The body is a raw JSON string, not `json=`: passing the value as a Python
    float would round it to ...98 during serialisation, so the fixture would
    destroy the precision before the adapter could preserve it and the test
    would be measuring itself.
    """
    body = """
    [
        {
            "contract_id": 7001,
            "title": "4ovArs",
            "type": "item_exchange",
            "status": "outstanding",
            "price": 99999999999999.99,
            "issuer_id": 2222,
            "assignee_id": 1111,
            "date_issued": "2026-08-17T12:00:00Z"
        }
    ]
    """
    responses.add(
        responses.GET,
        CONTRACTS_URL,
        body=body,
        status=200,
        content_type="application/json",
    )

    price = build_gateway().fetch_contracts(
        character_id=CHARACTER_ID, access_token="token"
    )[0].price

    assert isinstance(price, Decimal)
    assert price == Decimal("99999999999999.99")


@responses.activate
def test_every_page_is_fetched_when_x_pages_says_there_are_more():
    """The total is in a response header, not the body. Reading only page one
    silently drops most of the operator's contracts."""
    for page in (1, 2, 3):
        responses.add(
            responses.GET,
            CONTRACTS_URL,
            json=[{**CONTRACT_ROW, "contract_id": 7000 + page}],
            status=200,
            headers={"X-Pages": "3"},
        )

    contracts = build_gateway().fetch_contracts(
        character_id=CHARACTER_ID, access_token="token"
    )

    assert [c.contract_id for c in contracts] == [7001, 7002, 7003]
    assert len(responses.calls) == 3


@responses.activate
def test_a_single_page_response_makes_one_request():
    responses.add(responses.GET, CONTRACTS_URL, json=[CONTRACT_ROW], status=200)

    build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="token")

    assert len(responses.calls) == 1


@responses.activate
def test_the_access_token_and_user_agent_are_sent():
    responses.add(responses.GET, CONTRACTS_URL, json=[], status=200)

    build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="the-token")

    headers = responses.calls[0].request.headers
    assert headers["Authorization"] == "Bearer the-token"
    assert "eve-buyback" in headers["User-Agent"]


@responses.activate
def test_a_missing_price_reads_as_zero():
    """price is optional in the schema; a contract asking for nothing is
    below quote, not a crash."""
    row = {k: v for k, v in CONTRACT_ROW.items() if k != "price"}
    responses.add(responses.GET, CONTRACTS_URL, json=[row], status=200)

    contract = build_gateway().fetch_contracts(
        character_id=CHARACTER_ID, access_token="token"
    )[0]

    assert contract.price == Decimal("0")


@responses.activate
def test_a_contract_with_no_title_has_an_empty_quote_code():
    row = {k: v for k, v in CONTRACT_ROW.items() if k != "title"}
    responses.add(responses.GET, CONTRACTS_URL, json=[row], status=200)

    assert (
        build_gateway()
        .fetch_contracts(character_id=CHARACTER_ID, access_token="token")[0]
        .quote_code
        == ""
    )


@responses.activate
def test_a_403_with_no_scope_detail_suggests_reconnecting():
    """Not classified as a scope problem, because ESI says so explicitly when it
    is one. Whatever else a 403 means, re-linking is the useful first move."""
    responses.add(responses.GET, CONTRACTS_URL, json={"error": "forbidden"}, status=403)

    with pytest.raises(ContractSourceError) as exc:
        build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="token")

    message = str(exc.value)
    assert "forbidden" in message
    assert "connecting the character again" in message


@responses.activate
def test_a_server_error_is_a_contract_source_error():
    responses.add(responses.GET, CONTRACTS_URL, json={}, status=502)

    with pytest.raises(ContractSourceError):
        build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="token")


@responses.activate
def test_a_transport_failure_is_a_contract_source_error():
    responses.add(
        responses.GET, CONTRACTS_URL, body=requests.ConnectionError("down")
    )

    with pytest.raises(ContractSourceError):
        build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="token")


@responses.activate
def test_an_unexpected_contract_shape_names_the_problem():
    responses.add(responses.GET, CONTRACTS_URL, json=[{"contract_id": 1}], status=200)

    with pytest.raises(ContractSourceError) as exc:
        build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="token")

    assert "contract" in str(exc.value).lower()


@responses.activate
def test_non_json_is_a_contract_source_error():
    responses.add(
        responses.GET, CONTRACTS_URL, body="<html>gateway timeout</html>", status=200
    )

    with pytest.raises(ContractSourceError):
        build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="token")


@responses.activate
def test_items_map_onto_domain_lines():
    responses.add(
        responses.GET,
        items_url(7001),
        json=[
            {
                "record_id": 1,
                "type_id": 34,
                "quantity": 1000,
                "is_included": True,
                "is_singleton": False,
            },
            {
                "record_id": 2,
                "type_id": 638,
                "quantity": 1,
                "is_included": False,
                "is_singleton": True,
                "raw_quantity": -1,
            },
        ],
        status=200,
    )

    lines = build_gateway().fetch_items(
        character_id=CHARACTER_ID, contract_id=7001, access_token="token"
    )

    assert lines[0] == ContractItemLine(
        type_id=34, quantity=1000, is_included=True, is_singleton=False
    )
    assert lines[1].is_included is False
    assert lines[1].is_singleton is True


@responses.activate
def test_an_unexpected_item_shape_names_the_problem():
    responses.add(responses.GET, items_url(7001), json=[{"record_id": 1}], status=200)

    with pytest.raises(ContractSourceError) as exc:
        build_gateway().fetch_items(
            character_id=CHARACTER_ID, contract_id=7001, access_token="token"
        )

    assert "item" in str(exc.value).lower()


@responses.activate
def test_names_are_resolved_in_one_batched_request():
    responses.add(
        responses.POST,
        NAMES_URL,
        json=[
            {"id": 2222, "name": "Seller One", "category": "character"},
            {"id": 4444, "name": "Seller Two", "category": "character"},
        ],
        status=200,
    )

    names = build_gateway().resolve_names([2222, 4444, 2222])

    assert names == {2222: "Seller One", 4444: "Seller Two"}
    assert len(responses.calls) == 1


def test_resolving_no_ids_makes_no_request():
    assert build_gateway().resolve_names([]) == {}


@responses.activate
def test_a_name_lookup_failure_returns_empty_rather_than_failing_the_check():
    """Cosmetic data must never break the page; the raw id is shown instead."""
    responses.add(responses.POST, NAMES_URL, json={}, status=500)

    assert build_gateway().resolve_names([2222]) == {}


# X-Compatibility-Date is declared `required: true` on every ESI operation, and
# CCP publishes the accepted values at https://esi.evetech.net/meta/compatibility-dates
# The date pins which revision of the API answers, so it belongs in every request
# and must be pinned deliberately rather than left to a server-side default.
COMPAT_DATE = "2026-08-04"


@responses.activate
def test_the_compatibility_date_is_sent_on_the_contracts_request():
    responses.add(responses.GET, CONTRACTS_URL, json=[], status=200)

    build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="t")

    assert responses.calls[0].request.headers["X-Compatibility-Date"] == COMPAT_DATE


@responses.activate
def test_the_compatibility_date_is_sent_on_the_items_request():
    responses.add(responses.GET, items_url(7001), json=[], status=200)

    build_gateway().fetch_items(
        character_id=CHARACTER_ID, contract_id=7001, access_token="t"
    )

    assert responses.calls[0].request.headers["X-Compatibility-Date"] == COMPAT_DATE


@responses.activate
def test_the_compatibility_date_is_sent_on_the_name_lookup():
    """Unauthenticated, but the header is required on that operation too."""
    responses.add(responses.POST, NAMES_URL, json=[], status=200)

    build_gateway().resolve_names([2222])

    assert responses.calls[0].request.headers["X-Compatibility-Date"] == COMPAT_DATE


@responses.activate
def test_the_compatibility_date_is_configurable():
    """Pinned, but overridable, so moving to a newer revision is a config change."""
    responses.add(responses.GET, CONTRACTS_URL, json=[], status=200)

    gateway = EsiContractGateway(
        user_agent="eve-buyback tests", compatibility_date="2025-09-30"
    )
    gateway.fetch_contracts(character_id=CHARACTER_ID, access_token="t")

    assert responses.calls[0].request.headers["X-Compatibility-Date"] == "2025-09-30"


# Verified against live ESI: a token lacking the scope is answered with 401, not
# 403, and the body names the scope that was needed:
#   {"error":"Unauthorized - Token is not valid for any required scope:
#             esi-contracts.read_character_contracts.v1"}
# Discarding that body left the operator with a bare "ESI returned 401", which
# says nothing about the cause or the fix.
SCOPE_401 = {
    "error": (
        "Unauthorized - Token is not valid for any required scope: "
        "esi-contracts.read_character_contracts.v1"
    )
}


@responses.activate
def test_a_401_about_scope_is_reported_as_a_scope_rejection():
    responses.add(responses.GET, CONTRACTS_URL, json=SCOPE_401, status=401)

    with pytest.raises(ScopeRejected) as exc:
        build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="t")

    message = str(exc.value)
    assert "esi-contracts.read_character_contracts.v1" in message, (
        "ESI names the scope it needs; that is the single most useful part"
    )
    assert "ESI_SCOPES" in message, "the message should say what to change"


@responses.activate
def test_a_401_not_about_scope_is_a_plain_contract_source_error():
    """An expired or malformed token is a different problem with a different fix."""
    responses.add(
        responses.GET,
        CONTRACTS_URL,
        json={"error": "Unauthorized - Invalid token"},
        status=401,
    )

    with pytest.raises(ContractSourceError) as exc:
        build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="t")

    assert not isinstance(exc.value, ScopeRejected)
    assert "Invalid token" in str(exc.value)


@responses.activate
def test_esi_error_bodies_are_included_in_the_message():
    responses.add(
        responses.GET,
        CONTRACTS_URL,
        json={"error": "Internal Server Error - unhandled"},
        status=500,
    )

    with pytest.raises(ContractSourceError) as exc:
        build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="t")

    assert "unhandled" in str(exc.value)


@responses.activate
def test_a_403_mentioning_scope_is_still_a_scope_rejection():
    responses.add(responses.GET, CONTRACTS_URL, json=SCOPE_401, status=403)

    with pytest.raises(ScopeRejected):
        build_gateway().fetch_contracts(character_id=CHARACTER_ID, access_token="t")
