"""Value objects the verification logic compares.

Neither ESI payloads nor Django models: a contract and a quote both get
flattened into these first, so verification depends on nothing but plain data.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

# ESI enum members this code cares about, from
# https://esi.evetech.net/meta/openapi.json
ITEM_EXCHANGE = "item_exchange"
STATUS_OUTSTANDING = "outstanding"


@dataclass(frozen=True)
class ContractItemLine:
    """One line of a contract's contents.

    is_included is false when the issuer is *asking for* the item rather than
    submitting it. Every line of a legitimate buyback contract is true.
    """

    type_id: int
    quantity: int
    is_included: bool
    is_singleton: bool


@dataclass(frozen=True)
class ContractSnapshot:
    contract_id: int
    title: str
    contract_type: str
    status: str
    price: Decimal
    issuer_id: int
    assignee_id: int
    date_issued: datetime

    @property
    def quote_code(self) -> str:
        """The quote code the seller claims this contract fulfils.

        ESI calls it `title`; in the game client it is the contract Description
        field, which is where the quote page tells sellers to paste the code.
        """
        return self.title.strip()


@dataclass(frozen=True)
class QuoteLine:
    """type_id is None for an unparseable paste line, which was never offered."""

    type_id: int | None
    quantity: int


@dataclass(frozen=True)
class QuoteSnapshot:
    code: str
    total_value: Decimal
    created_at: datetime
    contract_days: int
    lines: tuple[QuoteLine, ...]

    @property
    def offer_expires_at(self) -> datetime:
        """The end of the window the quote page advertised to the seller.

        Mirrors Quote.contract_expires_at. A contract issued after this carries
        prices older than the terms it was offered under.
        """
        return self.created_at + timedelta(days=self.contract_days)
