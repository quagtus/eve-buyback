"""EVE-style number formatting.

The game separates thousands with spaces, so these deliberately bypass Django's
locale-aware formatting: an ISK figure reads the same for every visitor, which
is what a player copying it into the client expects.

Values are handled as Decimal rather than float. Converting through float loses
a cent around 1e14 — `Decimal("99999999999999.99")` renders as `...999.98` —
and this codebase already fixed the same class of bug in the Janice adapter.
"""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

THIN_SPACE = " "


def _to_decimal(value):
    """Coerce anything template-ish to Decimal, or None if it is not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


@register.filter
def isk(value):
    """Format a number as ISK with space-separated thousands.

    Example: 123456789.50 -> "123 456 789.50 ISK"
    """
    amount = _to_decimal(value)
    if amount is None:
        return "0.00 ISK"
    return f"{amount:,.2f}".replace(",", THIN_SPACE) + " ISK"


@register.filter
def sp(value):
    """Format a number as SP with space-separated thousands.

    Example: 12345678 -> "12 345 678 SP"
    """
    amount = _to_decimal(value)
    if amount is None:
        return "0 SP"
    return f"{int(amount):,}".replace(",", THIN_SPACE) + " SP"


@register.filter
def num_fmt(value):
    """Format a number with space-separated thousands, no suffix.

    Whole numbers lose their decimals: 12345678 -> "12 345 678";
    fractional ones keep two: 1234.5 -> "1 234.50".
    """
    amount = _to_decimal(value)
    if amount is None:
        return "0"
    if amount == amount.to_integral_value():
        return f"{int(amount):,}".replace(",", THIN_SPACE)
    return f"{amount:,.2f}".replace(",", THIN_SPACE)
