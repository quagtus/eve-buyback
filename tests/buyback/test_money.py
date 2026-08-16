from decimal import Decimal

from buyback.domain.money import line_total, sum_totals


def test_applies_percent_and_quantity():
    assert line_total(Decimal("100.00"), 3, Decimal("80.00")) == Decimal("240.00")


def test_rounds_half_up_to_two_places():
    # 1.005 * 1 * 100% -> 1.01, not 1.00 (banker's rounding would give 1.00)
    assert line_total(Decimal("1.005"), 1, Decimal("100.00")) == Decimal("1.01")


def test_zero_percent_yields_zero():
    assert line_total(Decimal("999999.99"), 100, Decimal("0")) == Decimal("0.00")


def test_result_always_has_two_decimal_places():
    assert str(line_total(Decimal("10"), 1, Decimal("50.00"))) == "5.00"


def test_total_is_the_sum_of_already_rounded_lines():
    """Displayed lines must add up to the displayed total, exactly."""
    lines = [
        line_total(Decimal("0.333"), 1, Decimal("100.00")),
        line_total(Decimal("0.333"), 1, Decimal("100.00")),
        line_total(Decimal("0.333"), 1, Decimal("100.00")),
    ]

    assert lines == [Decimal("0.33")] * 3
    assert sum_totals(lines) == Decimal("0.99")


def test_sum_of_nothing_is_zero():
    assert sum_totals([]) == Decimal("0.00")
