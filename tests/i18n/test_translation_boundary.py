from decimal import Decimal

import pytest
from django.test import Client
from django.test.utils import override_settings
from django.utils import translation

from buyback.models import Snapshot, SnapshotItem
from buyback.templatetags.buyback_labels import flag_reason_label, price_source_label


class FakeItem:
    def __init__(self, kind="", label="", code=None):
        self.price_source_kind = kind
        self.price_source_label = label
        self.flag_reason_code = code


def test_system_label_changes_under_an_active_locale():
    with translation.override("eo"):
        translated = price_source_label(FakeItem("BLACKLIST", ""))

    with translation.override("en"):
        english = price_source_label(FakeItem("BLACKLIST", ""))

    assert english == "Blacklisted"
    assert translated == "Malpermesita"
    assert translated != english


def test_rule_name_is_identical_in_every_locale():
    """Admin-authored names are data, not UI. They must never translate."""
    with translation.override("eo"):
        translated = price_source_label(FakeItem("CUSTOM", "Raven Special"))
    with translation.override("en"):
        english = price_source_label(FakeItem("CUSTOM", "Raven Special"))

    assert translated == english == "Raven Special"


@pytest.mark.django_db
def test_eve_item_names_are_never_translated_on_the_quote_page():
    snapshot = Snapshot.objects.create(
        code="I18NTEST", total_value=Decimal("100.00"), contract_to="Corp"
    )
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=638,
        type_name="Raven",
        quantity=1,
        unit_price=Decimal("100.00"),
        percent_applied=Decimal("100.00"),
        price_source_kind="CUSTOM",
        price_source_label="Raven Special",
        line_total=Decimal("100.00"),
    )
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=587,
        type_name="Rifter",
        quantity=1,
        unit_price=Decimal("0.00"),
        percent_applied=Decimal("0.00"),
        price_source_kind="BLACKLIST",
        price_source_label="",
        line_total=Decimal("0.00"),
        is_flagged=True,
        flag_reason_code="BLACKLISTED",
    )

    # LANGUAGES is widened only here: LocaleMiddleware refuses to activate a
    # locale that is not configured, and production ships English alone.
    with override_settings(
        ALLOWED_HOSTS=["testserver"],
        LANGUAGES=[("en", "English"), ("eo", "Esperanto")],
    ):
        client = Client()
        client.cookies["django_language"] = "eo"
        body = client.get("/quote/I18NTEST/").content.decode()

    # EVE data and the operator's rule name survive verbatim...
    assert "Raven" in body
    assert "Raven Special" in body
    # ...while buyback's own label is translated.
    assert "Malpermesita" in body


@pytest.mark.django_db
def test_production_languages_offers_english_only(settings):
    """Guard: the pseudo-locale must never leak into the shipped switcher."""
    assert [code for code, _name in settings.LANGUAGES] == ["en"]
