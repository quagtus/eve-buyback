"""Port for whatever prices items. Janice is one implementation."""

from decimal import Decimal
from typing import Protocol

from buyback.domain.appraisal import AppraisalResult


class AppraisalError(RuntimeError):
    """Raised when the upstream pricing service cannot be used."""


class PriceAppraisalGateway(Protocol):
    def create_appraisal(self, raw_text: str) -> AppraisalResult:
        """Price a raw pasted item list and persist it upstream.

        Raises AppraisalError on transport failure or an unusable response.
        """
        ...

    def price_types(self, type_ids) -> dict[int, Decimal]:
        """Current unit price per type id, for types priced without a paste.

        Types the upstream service does not price are absent from the result
        rather than present at zero: a missing price and a free item must not be
        indistinguishable.

        Raises AppraisalError on transport failure or an unusable response.
        """
        ...
