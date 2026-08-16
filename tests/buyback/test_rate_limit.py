from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse

from buyback.domain.appraisal import AppraisalItem, AppraisalResult


class StubGateway:
    def __init__(self):
        self.calls = 0

    def create_appraisal(self, raw_text):
        self.calls += 1
        return AppraisalResult(
            code=f"code{self.calls}",
            items=(
                AppraisalItem(
                    type_id=638, name="Raven", quantity=1, unit_price=Decimal("10.00")
                ),
            ),
            failures=(),
        )


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_submissions_beyond_the_limit_are_blocked(client, monkeypatch, settings):
    settings.BUYBACK_RATE_LIMIT = "2/h"
    gateway = StubGateway()
    monkeypatch.setattr("buyback.views.build_default_gateway", lambda: gateway)

    first = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})
    second = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})
    third = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})

    assert first.status_code == 302
    assert second.status_code == 302
    assert third.status_code == 429
    # The blocked request must never reach Janice.
    assert gateway.calls == 2
