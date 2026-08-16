from decimal import Decimal

from buyback.domain.appraisal import AppraisalItem, AppraisalResult


def test_result_reports_whether_it_has_priceable_items():
    empty = AppraisalResult(code="abc123", items=(), failures=("garbage line",))
    assert empty.has_items is False

    populated = AppraisalResult(
        code="abc123",
        items=(
            AppraisalItem(
                type_id=638, name="Raven", quantity=1, unit_price=Decimal("300000000")
            ),
        ),
        failures=(),
    )
    assert populated.has_items is True


def test_items_are_immutable():
    item = AppraisalItem(
        type_id=638, name="Raven", quantity=2, unit_price=Decimal("1.00")
    )
    try:
        item.quantity = 5
    except Exception as exc:
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("AppraisalItem must be frozen")
