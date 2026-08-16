"""EVE number formatting.

These deliberately bypass Django's locale formatting: a player copying an ISK
figure into the game client should see the same separators regardless of their
browser language.
"""

from decimal import Decimal

import pytest

from buyback.templatetags.eve_formats import isk, num_fmt, sp


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("123456789.50"), "123 456 789.50 ISK"),
        (Decimal("0"), "0.00 ISK"),
        (Decimal("999.9"), "999.90 ISK"),
        (Decimal("1000"), "1 000.00 ISK"),
    ],
)
def test_isk_groups_thousands_with_spaces(value, expected):
    assert isk(value) == expected


def test_isk_is_exact_at_large_values():
    """float() loses a cent near 1e14; Decimal does not.

    Regression guard: the same class of bug was already fixed once in the
    Janice adapter, where JSON parsing routed prices through float.
    """
    assert isk(Decimal("99999999999999.99")) == "99 999 999 999 999.99 ISK"


@pytest.mark.parametrize("junk", [None, "", "abc", [], {}])
def test_isk_degrades_rather_than_raising(junk):
    """A template filter that raises takes the whole page down."""
    assert isk(junk) == "0.00 ISK"


def test_isk_accepts_strings_and_ints():
    assert isk("1234.5") == "1 234.50 ISK"
    assert isk(1234) == "1 234.00 ISK"


@pytest.mark.parametrize(
    "value,expected",
    [(12345678, "12 345 678 SP"), (0, "0 SP"), (Decimal("5500000.9"), "5 500 000 SP")],
)
def test_sp_formats_whole_skillpoints(value, expected):
    assert sp(value) == expected


@pytest.mark.parametrize("junk", [None, "abc", []])
def test_sp_degrades_rather_than_raising(junk):
    assert sp(junk) == "0 SP"


@pytest.mark.parametrize(
    "value,expected",
    [
        (12345678, "12 345 678"),
        (Decimal("1234.5"), "1 234.50"),
        (Decimal("1000.00"), "1 000"),
        (0, "0"),
    ],
)
def test_num_fmt_drops_decimals_only_when_whole(value, expected):
    assert num_fmt(value) == expected


@pytest.mark.parametrize("junk", [None, "abc", {}])
def test_num_fmt_degrades_rather_than_raising(junk):
    assert num_fmt(junk) == "0"


def test_booleans_are_not_treated_as_numbers():
    """bool is an int subclass; True would otherwise render as '1.00 ISK'."""
    assert isk(True) == "0.00 ISK"
    assert num_fmt(False) == "0"
