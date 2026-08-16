"""Port for whatever prices items. Janice is one implementation."""

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
