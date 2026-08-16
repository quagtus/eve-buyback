from decimal import Decimal

import pytest

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.domain.gateway import AppraisalError
from buyback.models import Snapshot
from buyback.services import EmptyAppraisalError, generate_snapshot
from catalog.models import EveCategory, EveGroup, EveType
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule
from siteconfig.models import SiteConfig


class StubGateway:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.received_text = None

    def create_appraisal(self, raw_text):
        self.received_text = raw_text
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def configured(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    frigate = EveGroup.objects.create(id=25, name="Frigate", category=ship)
    EveType.objects.create(id=638, name="Raven", group=battleship)
    rifter = EveType.objects.create(id=587, name="Rifter", group=frigate)

    CategoryDefaultPercent.objects.create(category=ship, percent=Decimal("80.00"))
    rule = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    rule.groups.add(battleship)
    BlacklistEntry.objects.create(type=rifter)

    config = SiteConfig.load()
    config.contract_to = "Buyback Corp"
    config.contract_instructions = "Contract to Buyback Corp in Jita."
    config.save()
    return config


@pytest.mark.django_db
def test_generates_a_snapshot_with_frozen_values(configured):
    gateway = StubGateway(
        AppraisalResult(
            code="4ovArs",
            items=(
                AppraisalItem(
                    type_id=638, name="Raven", quantity=2, unit_price=Decimal("100.00")
                ),
            ),
            failures=(),
        )
    )

    snapshot = generate_snapshot("Raven\t2", gateway)

    assert snapshot.pk == "4ovArs"
    assert snapshot.total_value == Decimal("140.00")
    assert snapshot.contract_to == "Buyback Corp"
    assert gateway.received_text == "Raven\t2"

    item = snapshot.items.get()
    assert item.percent_applied == Decimal("70.00")
    assert item.price_source == "Battleships"


@pytest.mark.django_db
def test_later_rule_changes_do_not_alter_an_existing_snapshot(configured):
    gateway = StubGateway(
        AppraisalResult(
            code="4ovArs",
            items=(
                AppraisalItem(
                    type_id=638, name="Raven", quantity=1, unit_price=Decimal("100.00")
                ),
            ),
            failures=(),
        )
    )
    snapshot = generate_snapshot("Raven\t1", gateway)
    assert snapshot.total_value == Decimal("70.00")

    CustomRule.objects.filter(label="Battleships").update(percent=Decimal("10.00"))
    configured.contract_to = "Someone Else"
    configured.save()

    reloaded = Snapshot.objects.get(pk="4ovArs")
    assert reloaded.total_value == Decimal("70.00")
    assert reloaded.items.get().percent_applied == Decimal("70.00")
    assert reloaded.contract_to == "Buyback Corp"


@pytest.mark.django_db
def test_blacklisted_and_unparseable_lines_are_persisted_as_flagged(configured):
    gateway = StubGateway(
        AppraisalResult(
            code="abc999",
            items=(
                AppraisalItem(
                    type_id=587, name="Rifter", quantity=3, unit_price=Decimal("50.00")
                ),
            ),
            failures=("garbage",),
        )
    )

    snapshot = generate_snapshot("Rifter\t3\ngarbage", gateway)

    flagged = list(snapshot.items.all())
    assert len(flagged) == 2
    assert all(item.is_flagged for item in flagged)
    assert snapshot.total_value == Decimal("0.00")


@pytest.mark.django_db
def test_appraisal_with_no_items_raises_and_persists_nothing(configured):
    gateway = StubGateway(
        AppraisalResult(code="abc999", items=(), failures=("garbage",))
    )

    with pytest.raises(EmptyAppraisalError):
        generate_snapshot("garbage", gateway)

    assert Snapshot.objects.count() == 0


@pytest.mark.django_db
def test_gateway_failure_persists_nothing(configured):
    gateway = StubGateway(error=AppraisalError("boom"))

    with pytest.raises(AppraisalError):
        generate_snapshot("Raven\t1", gateway)

    assert Snapshot.objects.count() == 0


@pytest.mark.django_db
def test_type_id_absent_from_catalog_is_flagged_via_real_classifications_query(
    configured,
):
    UNKNOWN_TYPE_ID = 99999999
    gateway = StubGateway(
        AppraisalResult(
            code="4ovArs",
            items=(
                AppraisalItem(
                    type_id=638, name="Raven", quantity=2, unit_price=Decimal("100.00")
                ),
                AppraisalItem(
                    type_id=UNKNOWN_TYPE_ID,
                    name="Mystery Box",
                    quantity=1,
                    unit_price=Decimal("10.00"),
                ),
            ),
            failures=(),
        )
    )

    snapshot = generate_snapshot("Raven\t2\nMystery Box\t1", gateway)

    assert Snapshot.objects.count() == 1
    items = {item.type_id: item for item in snapshot.items.all()}

    known = items[638]
    assert known.is_flagged is False
    assert known.line_total == Decimal("140.00")

    unknown = items[UNKNOWN_TYPE_ID]
    assert unknown.is_flagged is True
    assert unknown.flag_reason == "Unrecognized item"
    assert unknown.line_total == Decimal("0.00")

    assert snapshot.total_value == Decimal("140.00")
