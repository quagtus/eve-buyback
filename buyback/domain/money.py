"""ISK arithmetic. Decimal only — never float.

`percent` is in percentage points (Decimal("80.00") == 80%). This is the only
module that divides by 100.

Lines are rounded before summing so the rendered line items always add up to
the rendered total.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

CENTS = Decimal("0.01")
HUNDRED = Decimal("100")


def quantize_isk(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def line_total(unit_price: Decimal, quantity: int, percent: Decimal) -> Decimal:
    return quantize_isk(unit_price * Decimal(quantity) * percent / HUNDRED)


def sum_totals(values: Iterable[Decimal]) -> Decimal:
    return quantize_isk(sum(values, Decimal("0")))
