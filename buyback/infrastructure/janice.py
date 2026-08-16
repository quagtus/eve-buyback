"""Janice implementation of PriceAppraisalGateway.

Schema verified against https://janice.e-351.com/api/rest/v2/swagger.json:
  request  : raw text body, Content-Type text/plain, X-ApiKey header
  response : {code, created, expires, failures (newline string|null), items[]}
  item     : {amount, itemType:{eid,name}, effectivePrices:{buyPrice,splitPrice,sellPrice}}

`effectivePrices` already reflects the requested pricingVariant, so reading
effectivePrices.<basis>Price honours both configured settings.
"""

from decimal import Decimal

import requests

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.domain.gateway import AppraisalError

PRICE_FIELDS = {
    "buy": "buyPrice",
    "split": "splitPrice",
    "sell": "sellPrice",
}

TIMEOUT_SECONDS = 30


class JaniceAppraisalGateway:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        market_id: int,
        pricing_basis: str,
        pricing_variant: str,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._market_id = market_id
        self._pricing_basis = pricing_basis
        self._pricing_variant = pricing_variant

    def create_appraisal(self, raw_text: str) -> AppraisalResult:
        try:
            response = requests.post(
                f"{self._base_url}/appraisal",
                params={
                    "market": self._market_id,
                    "designation": "wtb",
                    "pricing": self._pricing_basis,
                    "pricingVariant": self._pricing_variant,
                    "persist": "true",
                    "compactize": "true",
                    # Our percentages are per-item; Janice's flat one must stay 1.
                    "pricePercentage": 1,
                },
                headers={
                    "X-ApiKey": self._api_key,
                    "Content-Type": "text/plain",
                },
                data=raw_text.encode("utf-8"),
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise AppraisalError(f"Janice request failed: {exc}") from exc
        except ValueError as exc:
            raise AppraisalError("Janice returned a non-JSON response") from exc

        return self._to_result(payload)

    def _to_result(self, payload: dict) -> AppraisalResult:
        code = payload.get("code")
        if not code:
            raise AppraisalError("Janice response contained no appraisal code")

        price_field = PRICE_FIELDS[self._pricing_basis]
        items = []
        for entry in payload.get("items") or []:
            item_type = entry.get("itemType") or {}
            prices = entry.get("effectivePrices") or {}
            raw_price = prices.get(price_field)
            if item_type.get("eid") is None or raw_price is None:
                continue
            items.append(
                AppraisalItem(
                    type_id=int(item_type["eid"]),
                    name=item_type.get("name") or "",
                    quantity=int(entry.get("amount") or 0),
                    unit_price=Decimal(str(raw_price)),
                )
            )

        raw_failures = payload.get("failures") or ""
        failures = tuple(
            line.strip() for line in raw_failures.splitlines() if line.strip()
        )

        return AppraisalResult(code=code, items=tuple(items), failures=failures)
