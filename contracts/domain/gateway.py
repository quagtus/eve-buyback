"""Port for whatever supplies contracts. ESI is one implementation.

Mirrors buyback.domain.gateway: the domain states what it needs, and an adapter
in infrastructure provides it. A corporation contract source, or a recorded
fixture for local development, is a second implementation rather than a change
here.
"""

from typing import Protocol, runtime_checkable

from contracts.domain.contract import ContractItemLine, ContractSnapshot


class ContractSourceError(RuntimeError):
    """Raised when the contract source cannot be used or returned nonsense."""


class ScopeRejected(ContractSourceError):
    """The credential is valid but lacks permission; the operator must re-link."""


@runtime_checkable
class ContractSourceGateway(Protocol):
    def fetch_contracts(
        self, *, character_id: int, access_token: str
    ) -> tuple[ContractSnapshot, ...]:
        """Every contract the character is a party to, in no particular order.

        Filtering by status is the caller's job.
        """
        ...

    def fetch_items(
        self, *, character_id: int, contract_id: int, access_token: str
    ) -> tuple[ContractItemLine, ...]:
        ...

    def resolve_names(self, ids) -> dict[int, str]:
        """Best effort. An empty dict is a valid answer, never an error."""
        ...
