from decimal import Decimal

import pytest
import responses

from buyback.domain.gateway import AppraisalError
from buyback.infrastructure.janice import JaniceAppraisalGateway

BASE_URL = "https://janice.test/api/rest/v2"
APPRAISAL_URL = f"{BASE_URL}/appraisal"

SAMPLE_RESPONSE = {
    "code": "4ovArs",
    "created": "2026-08-16T12:00:00Z",
    "expires": "2026-09-16T12:00:00Z",
    "failures": "not an item\nalso not an item",
    "items": [
        {
            "amount": 2,
            "itemType": {"eid": 638, "name": "Raven"},
            "effectivePrices": {
                "buyPrice": 250000000.0,
                "splitPrice": 275000000.0,
                "sellPrice": 300000000.0,
            },
        },
        {
            "amount": 1000,
            "itemType": {"eid": 34, "name": "Tritanium"},
            "effectivePrices": {
                "buyPrice": 4.5,
                "splitPrice": 5.0,
                "sellPrice": 5.5,
            },
        },
    ],
}


def build_gateway(basis="split"):
    return JaniceAppraisalGateway(
        api_key="test-key",
        base_url=BASE_URL,
        market_id=2,
        pricing_basis=basis,
        pricing_variant="immediate",
    )


@responses.activate
def test_parses_code_items_and_failures():
    responses.add(responses.POST, APPRAISAL_URL, json=SAMPLE_RESPONSE, status=200)

    result = build_gateway().create_appraisal("Raven 2")

    assert result.code == "4ovArs"
    assert len(result.items) == 2
    assert result.items[0].type_id == 638
    assert result.items[0].name == "Raven"
    assert result.items[0].quantity == 2
    assert result.items[0].unit_price == Decimal("275000000.0")
    assert result.failures == ("not an item", "also not an item")


@responses.activate
def test_pricing_basis_selects_the_matching_price_field():
    responses.add(responses.POST, APPRAISAL_URL, json=SAMPLE_RESPONSE, status=200)

    result = build_gateway(basis="sell").create_appraisal("Raven 2")

    assert result.items[0].unit_price == Decimal("300000000.0")


@responses.activate
def test_sends_required_headers_and_query_parameters():
    responses.add(responses.POST, APPRAISAL_URL, json=SAMPLE_RESPONSE, status=200)

    build_gateway().create_appraisal("Raven 2")

    request = responses.calls[0].request
    assert request.headers["X-ApiKey"] == "test-key"
    assert request.headers["Content-Type"] == "text/plain"
    assert request.body == b"Raven 2"

    from urllib.parse import parse_qs, urlparse

    params = parse_qs(urlparse(request.url).query)
    assert params["market"] == ["2"]
    assert params["persist"] == ["true"]
    assert params["compactize"] == ["true"]
    assert params["designation"] == ["wtb"]
    assert params["pricing"] == ["split"]
    assert params["pricingVariant"] == ["immediate"]
    # Must stay 1: Janice's own percentage would double-discount every quote.
    assert params["pricePercentage"] == ["1"]


@responses.activate
def test_null_failures_becomes_empty_tuple():
    payload = {**SAMPLE_RESPONSE, "failures": None}
    responses.add(responses.POST, APPRAISAL_URL, json=payload, status=200)

    assert build_gateway().create_appraisal("Raven 2").failures == ()


@responses.activate
def test_http_error_raises_appraisal_error():
    responses.add(responses.POST, APPRAISAL_URL, json={"error": "nope"}, status=500)

    with pytest.raises(AppraisalError):
        build_gateway().create_appraisal("Raven 2")


@responses.activate
def test_missing_code_raises_appraisal_error():
    payload = {**SAMPLE_RESPONSE, "code": None}
    responses.add(responses.POST, APPRAISAL_URL, json=payload, status=200)

    with pytest.raises(AppraisalError):
        build_gateway().create_appraisal("Raven 2")


@responses.activate
def test_high_precision_price_survives_without_float_rounding():
    # Raw JSON body (not the json= kwarg) so the number is never re-serialized
    # through a Python float before hitting our parser.
    body = """
    {
        "code": "4ovArs",
        "created": "2026-08-16T12:00:00Z",
        "expires": "2026-09-16T12:00:00Z",
        "failures": null,
        "items": [
            {
                "amount": 1,
                "itemType": {"eid": 638, "name": "Raven"},
                "effectivePrices": {
                    "buyPrice": 100000000000000.01,
                    "splitPrice": 100000000000000.01,
                    "sellPrice": 100000000000000.01
                }
            }
        ]
    }
    """
    responses.add(
        responses.POST,
        APPRAISAL_URL,
        body=body,
        status=200,
        content_type="application/json",
    )

    result = build_gateway().create_appraisal("Raven 1")

    assert result.items[0].unit_price == Decimal("100000000000000.01")


@responses.activate
def test_malformed_item_entry_is_surfaced_as_a_failure_not_dropped():
    payload = {
        "code": "4ovArs",
        "created": "2026-08-16T12:00:00Z",
        "expires": "2026-09-16T12:00:00Z",
        "failures": None,
        "items": [
            {
                "amount": 2,
                "itemType": {"eid": 638, "name": "Raven"},
                "effectivePrices": {
                    "buyPrice": 250000000.0,
                    "splitPrice": 275000000.0,
                    "sellPrice": 300000000.0,
                },
            },
            {
                "amount": 1,
                "itemType": None,
                "effectivePrices": {
                    "buyPrice": 1.0,
                    "splitPrice": 1.0,
                    "sellPrice": 1.0,
                },
            },
        ],
    }
    responses.add(responses.POST, APPRAISAL_URL, json=payload, status=200)

    result = build_gateway().create_appraisal("Raven 2")

    assert len(result.items) == 1
    assert result.items[0].type_id == 638
    assert len(result.failures) == 1
    assert "unknown" in result.failures[0]


@responses.activate
def test_invalid_pricing_basis_raises_appraisal_error_not_key_error():
    responses.add(responses.POST, APPRAISAL_URL, json=SAMPLE_RESPONSE, status=200)

    gateway = build_gateway(basis="not-a-real-basis")

    with pytest.raises(AppraisalError):
        gateway.create_appraisal("Raven 2")
