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

# The pricer endpoint returns both blocks and applies neither, so the adapter
# picks one. The appraisal endpoint resolves this server-side into
# effectivePrices, which is why only that call can ignore the distinction.
VARIANT_BLOCKS = {
    "immediate": "immediatePrices",
    "top5percent": "top5AveragePrices",
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
            # parse_float=Decimal: JSON numbers become Decimal directly, so
            # ISK prices never round-trip through a lossy binary float.
            payload = response.json(parse_float=Decimal)
        except requests.RequestException as exc:
            raise AppraisalError(f"Janice request failed: {exc}") from exc
        except ValueError as exc:
            raise AppraisalError("Janice returned a non-JSON response") from exc

        return self._to_result(payload)

    def _to_result(self, payload: dict) -> AppraisalResult:
        # A 200 response is not a guarantee of the expected shape. Everything
        # below that merely walks the payload (missing keys, wrong types) is
        # wrapped so a surprise shape becomes an AppraisalError the view
        # already knows how to turn into a friendly page, not a raw 500.
        # The explicit AppraisalError raises below are NOT caught here: they
        # are already the clear, specific error we want the caller to see.
        try:
            code = payload.get("code")
            if not code:
                raise AppraisalError("Janice response contained no appraisal code")

            price_field = PRICE_FIELDS.get(self._pricing_basis)
            if price_field is None:
                raise AppraisalError(
                    f"Unknown pricing basis: {self._pricing_basis!r}"
                )

            items = []
            unparseable = []
            for entry in payload.get("items") or []:
                item_type = entry.get("itemType") or {}
                prices = entry.get("effectivePrices") or {}
                raw_price = prices.get(price_field)
                if item_type.get("eid") is None or raw_price is None:
                    # Never drop it silently: surface it as a flagged zero-value
                    # line so the seller can see what was rejected and why.
                    name = item_type.get("name")
                    unparseable.append(f"Unparseable item entry: {name or 'unknown'}")
                    continue
                # raw_price already arrives as a Decimal (parse_float=Decimal
                # above); str() round-trip is redundant but harmless if that
                # ever changes.
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
            ) + tuple(unparseable)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AppraisalError(
                f"Janice returned an unexpected response shape: {exc}"
            ) from exc

        return AppraisalResult(code=code, items=tuple(items), failures=failures)

    def price_types(self, type_ids) -> dict[int, Decimal]:
        """Price types directly, without going through a paste.

        Used for reprocessing outputs: the seller pastes ore, and the minerals it
        yields have to be priced even though they never appear in the text.
        """
        wanted = sorted({int(type_id) for type_id in type_ids})
        if not wanted:
            return {}

        # Validated before the request so a misconfiguration fails immediately
        # rather than after a round trip.
        price_field = PRICE_FIELDS.get(self._pricing_basis)
        if price_field is None:
            raise AppraisalError(f"Unknown pricing basis: {self._pricing_basis!r}")
        block = VARIANT_BLOCKS.get(self._pricing_variant)
        if block is None:
            raise AppraisalError(
                f"Unknown pricing variant: {self._pricing_variant!r}"
            )

        try:
            response = requests.post(
                f"{self._base_url}/pricer",
                params={"market": self._market_id},
                headers={
                    "X-ApiKey": self._api_key,
                    "Content-Type": "text/plain",
                },
                data="\n".join(str(type_id) for type_id in wanted).encode("utf-8"),
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json(parse_float=Decimal)
        except requests.RequestException as exc:
            raise AppraisalError(f"Janice pricer request failed: {exc}") from exc
        except ValueError as exc:
            raise AppraisalError("Janice pricer returned a non-JSON response") from exc

        # A row missing its eid or price block is skipped rather than fatal: one
        # odd entry must not discard the prices of every other material in the
        # batch. The caller treats an absent price as unpriced, never as free.
        try:
            prices: dict[int, Decimal] = {}
            for entry in payload or []:
                eid = (entry.get("itemType") or {}).get("eid")
                raw = (entry.get(block) or {}).get(price_field)
                if eid is None or raw is None:
                    continue
                prices[int(eid)] = Decimal(str(raw))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AppraisalError(
                f"Janice pricer returned an unexpected response shape: {exc}"
            ) from exc

        return prices
