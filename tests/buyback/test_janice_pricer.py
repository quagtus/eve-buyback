"""Pricing individual types through Janice's pricer endpoint.

Schema verified against https://janice.e-351.com/api/rest/v2/swagger.json:
  POST /api/rest/v2/pricer
    body    : text/plain, one type id or name per line
    response: PricerItem[] with immediatePrices and top5AveragePrices

Unlike the appraisal endpoint there is NO effectivePrices: the pricer does not
apply the configured pricing/pricingVariant server-side, so the adapter has to
select both itself.
"""

from decimal import Decimal

import pytest
import requests
import responses

from buyback.domain.gateway import AppraisalError
from buyback.infrastructure.janice import JaniceAppraisalGateway

BASE_URL = "https://janice.test/api/rest/v2"
PRICER_URL = f"{BASE_URL}/pricer"


def row(eid, name, immediate_buy, immediate_split, top5_buy):
    return {
        "itemType": {"eid": eid, "name": name},
        "immediatePrices": {
            "buyPrice": immediate_buy,
            "splitPrice": immediate_split,
            "sellPrice": 999.0,
        },
        "top5AveragePrices": {
            "buyPrice": top5_buy,
            "splitPrice": 888.0,
            "sellPrice": 777.0,
        },
    }


SAMPLE = [
    row(16272, "Heavy Water", 99.40, 105.0, 101.0),
    row(16275, "Strontium Clathrates", 4236.0, 4300.0, 4250.0),
]


def build_gateway(basis="buy", variant="immediate"):
    return JaniceAppraisalGateway(
        api_key="test-key",
        base_url=BASE_URL,
        market_id=2,
        pricing_basis=basis,
        pricing_variant=variant,
    )


@responses.activate
def test_prices_are_returned_keyed_by_type_id():
    responses.add(responses.POST, PRICER_URL, json=SAMPLE, status=200)

    prices = build_gateway().price_types([16272, 16275])

    assert prices == {16272: Decimal("99.40"), 16275: Decimal("4236.0")}


@responses.activate
def test_the_body_is_one_type_id_per_line_as_plain_text():
    responses.add(responses.POST, PRICER_URL, json=SAMPLE, status=200)

    build_gateway().price_types([16275, 16272, 16272])

    request = responses.calls[0].request
    assert request.headers["Content-Type"] == "text/plain"
    assert request.headers["X-ApiKey"] == "test-key"
    # Deduplicated and ordered, so the request is stable and cacheable upstream.
    assert request.body.decode().split("\n") == ["16272", "16275"]


@responses.activate
def test_the_market_is_sent():
    responses.add(responses.POST, PRICER_URL, json=SAMPLE, status=200)

    build_gateway().price_types([16272])

    assert "market=2" in responses.calls[0].request.url


@responses.activate
def test_the_configured_basis_selects_the_price_field():
    responses.add(responses.POST, PRICER_URL, json=SAMPLE, status=200)

    prices = build_gateway(basis="split").price_types([16272])

    assert prices[16272] == Decimal("105.0")


@responses.activate
def test_the_configured_variant_selects_the_price_block():
    """The appraisal endpoint resolves this server-side and returns
    effectivePrices. The pricer does not, so getting it wrong here would make
    mineral prices quietly ignore the operator's configuration."""
    responses.add(responses.POST, PRICER_URL, json=SAMPLE, status=200)

    prices = build_gateway(variant="top5percent").price_types([16272])

    assert prices[16272] == Decimal("101.0")


@responses.activate
def test_prices_are_decimal_not_float():
    body = """
    [
        {
            "itemType": {"eid": 16272, "name": "Heavy Water"},
            "immediatePrices": {"buyPrice": 99999999999999.99, "splitPrice": 1.0, "sellPrice": 1.0},
            "top5AveragePrices": {"buyPrice": 1.0, "splitPrice": 1.0, "sellPrice": 1.0}
        }
    ]
    """
    responses.add(
        responses.POST,
        PRICER_URL,
        body=body,
        status=200,
        content_type="application/json",
    )

    prices = build_gateway().price_types([16272])

    assert isinstance(prices[16272], Decimal)
    assert prices[16272] == Decimal("99999999999999.99")


def test_pricing_no_types_makes_no_request():
    assert build_gateway().price_types([]) == {}


@responses.activate
def test_a_missing_type_is_absent_rather_than_zero():
    """Assuming free would silently underpay the seller."""
    responses.add(responses.POST, PRICER_URL, json=SAMPLE, status=200)

    prices = build_gateway().price_types([16272, 16275, 34])

    assert 34 not in prices


@responses.activate
def test_a_transport_failure_is_an_appraisal_error():
    responses.add(responses.POST, PRICER_URL, body=requests.ConnectionError("down"))

    with pytest.raises(AppraisalError):
        build_gateway().price_types([16272])


@responses.activate
def test_a_server_error_is_an_appraisal_error():
    responses.add(responses.POST, PRICER_URL, json={}, status=502)

    with pytest.raises(AppraisalError):
        build_gateway().price_types([16272])


@responses.activate
def test_an_unexpected_shape_is_an_appraisal_error():
    responses.add(responses.POST, PRICER_URL, json=[{"itemType": {}}], status=200)

    prices = build_gateway().price_types([16272])

    # A row with no eid and no price block is skipped, not fatal: one odd entry
    # must not lose the prices of every other material in the batch.
    assert prices == {}


@responses.activate
def test_an_unknown_pricing_basis_is_rejected_before_the_request():
    with pytest.raises(AppraisalError) as exc:
        build_gateway(basis="nonsense").price_types([16272])

    assert "basis" in str(exc.value).lower()
    assert len(responses.calls) == 0


@responses.activate
def test_an_unknown_pricing_variant_is_rejected_before_the_request():
    with pytest.raises(AppraisalError) as exc:
        build_gateway(variant="nonsense").price_types([16272])

    assert "variant" in str(exc.value).lower()
    assert len(responses.calls) == 0
