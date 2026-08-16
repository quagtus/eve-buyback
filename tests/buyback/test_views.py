from decimal import Decimal

import pytest
from django.urls import reverse

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.models import Snapshot, SnapshotItem


@pytest.fixture
def priced_snapshot(db):
    snapshot = Snapshot.objects.create(
        code="4ovArs",
        total_value=Decimal("140.00"),
        contract_to="Buyback Corp",
        contract_instructions="Contract to Buyback Corp in Jita.",
    )
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=638,
        type_name="Raven",
        quantity=2,
        unit_price=Decimal("100.00"),
        percent_applied=Decimal("70.00"),
        price_source_kind="CUSTOM",
        price_source_label="Battleships",
        line_total=Decimal("140.00"),
    )
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=587,
        type_name="Rifter",
        quantity=1,
        unit_price=Decimal("50.00"),
        percent_applied=Decimal("0.00"),
        price_source_kind="BLACKLIST",
        line_total=Decimal("0.00"),
        is_flagged=True,
        flag_reason_code="BLACKLISTED",
    )
    return snapshot


@pytest.mark.django_db
def test_form_page_renders(client):
    response = client.get(reverse("buyback:form"))

    assert response.status_code == 200
    assert b"<form" in response.content


@pytest.mark.django_db
def test_snapshot_page_shows_items_totals_and_flags(client, priced_snapshot):
    response = client.get(reverse("buyback:snapshot", args=["4ovArs"]))

    assert response.status_code == 200
    body = response.content.decode()
    assert "Raven" in body
    assert "140.00" in body
    assert "BLACKLISTED" in body
    assert "Buyback Corp" in body
    assert "janice.e-351.com/a/4ovArs" in body


@pytest.mark.django_db
def test_unknown_snapshot_returns_404(client):
    assert client.get(reverse("buyback:snapshot", args=["nope"])).status_code == 404


@pytest.mark.django_db
def test_submitting_redirects_to_the_new_snapshot(client, monkeypatch, settings):
    settings.BUYBACK_RATE_LIMIT = "1000/h"

    class StubGateway:
        def create_appraisal(self, raw_text):
            return AppraisalResult(
                code="newcode",
                items=(
                    AppraisalItem(
                        type_id=638, name="Raven", quantity=1, unit_price=Decimal("10.00")
                    ),
                ),
                failures=(),
            )

    monkeypatch.setattr("buyback.views.build_default_gateway", lambda: StubGateway())

    response = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})

    assert response.status_code == 302
    assert response.url == reverse("buyback:snapshot", args=["newcode"])


@pytest.mark.django_db
def test_empty_paste_is_rejected_without_calling_the_gateway(client, settings):
    settings.BUYBACK_RATE_LIMIT = "1000/h"

    response = client.post(reverse("buyback:submit"), {"raw_text": "   "})

    assert response.status_code == 200
    assert b"Paste" in response.content
    assert Snapshot.objects.count() == 0


@pytest.mark.django_db
def test_htmx_submit_returns_hx_redirect_header_instead_of_302(
    client, monkeypatch, settings
):
    """HTMX follows a 302 transparently and swaps the final body into #result,
    trapping the whole page inside a div and never updating the browser URL.
    On success, an HTMX request must instead get a non-redirect status carrying
    HX-Redirect so the client performs a real navigation to the permanent URL.
    """
    settings.BUYBACK_RATE_LIMIT = "1000/h"

    class StubGateway:
        def create_appraisal(self, raw_text):
            return AppraisalResult(
                code="htmxcode",
                items=(
                    AppraisalItem(
                        type_id=638, name="Raven", quantity=1, unit_price=Decimal("10.00")
                    ),
                ),
                failures=(),
            )

    monkeypatch.setattr("buyback.views.build_default_gateway", lambda: StubGateway())

    response = client.post(
        reverse("buyback:submit"),
        {"raw_text": "Raven\t1"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code in (200, 204)
    assert response.headers.get("HX-Redirect") == reverse(
        "buyback:snapshot", args=["htmxcode"]
    )
    # Must not be a redirect status; HTMX would just follow it via fetch again.
    assert response.status_code != 302


@pytest.mark.django_db
def test_duplicate_snapshot_code_renders_error_partial_instead_of_500(
    client, monkeypatch, settings
):
    settings.BUYBACK_RATE_LIMIT = "1000/h"

    class StubGateway:
        def create_appraisal(self, raw_text):
            return AppraisalResult(
                code="dupecode",
                items=(
                    AppraisalItem(
                        type_id=638, name="Raven", quantity=1, unit_price=Decimal("10.00")
                    ),
                ),
                failures=(),
            )

    monkeypatch.setattr("buyback.views.build_default_gateway", lambda: StubGateway())

    first = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})
    assert first.status_code == 302

    second = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})
    assert second.status_code == 200
    assert b"already exists" in second.content
    assert Snapshot.objects.filter(pk="dupecode").count() == 1


@pytest.mark.django_db
def test_non_htmx_submit_still_returns_a_plain_302(client, monkeypatch, settings):
    settings.BUYBACK_RATE_LIMIT = "1000/h"

    class StubGateway:
        def create_appraisal(self, raw_text):
            return AppraisalResult(
                code="plaincode",
                items=(
                    AppraisalItem(
                        type_id=638, name="Raven", quantity=1, unit_price=Decimal("10.00")
                    ),
                ),
                failures=(),
            )

    monkeypatch.setattr("buyback.views.build_default_gateway", lambda: StubGateway())

    response = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})

    assert response.status_code == 302
    assert response.url == reverse("buyback:snapshot", args=["plaincode"])
    assert "HX-Redirect" not in response.headers
