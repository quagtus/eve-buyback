"""Application layer: orchestrates gateway, rules, and persistence."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from buyback.domain.gateway import PriceAppraisalGateway
from buyback.domain.quote import build_quote
from buyback.infrastructure.janice import JaniceAppraisalGateway
from buyback.models import Snapshot, SnapshotItem
from catalog.models import EveType
from pricing.domain.ruleset import ItemClassification
from pricing.repositories import load_ruleset
from siteconfig.models import SiteConfig


class EmptyAppraisalError(RuntimeError):
    """Nothing in the paste could be priced, so there is nothing to snapshot."""


def build_default_gateway(config: SiteConfig | None = None) -> JaniceAppraisalGateway:
    config = config or SiteConfig.load()
    return JaniceAppraisalGateway(
        api_key=settings.JANICE_API_KEY,
        base_url=settings.JANICE_BASE_URL,
        market_id=config.market_id,
        pricing_basis=config.pricing_basis,
        pricing_variant=config.pricing_variant,
    )


def _classifications(type_ids) -> dict[int, ItemClassification]:
    rows = EveType.objects.filter(id__in=type_ids).values(
        "id", "group_id", "group__category_id"
    )
    return {
        row["id"]: ItemClassification(
            type_id=row["id"],
            group_id=row["group_id"],
            category_id=row["group__category_id"],
        )
        for row in rows
    }


def generate_snapshot(
    raw_text: str, gateway: PriceAppraisalGateway | None = None
) -> Snapshot:
    config = SiteConfig.load()
    gateway = gateway or build_default_gateway(config)

    appraisal = gateway.create_appraisal(raw_text)
    if not appraisal.has_items:
        raise EmptyAppraisalError("Janice could not price any item in that list.")

    ruleset = load_ruleset()
    classifications = _classifications({item.type_id for item in appraisal.items})
    quote = build_quote(appraisal, ruleset, classifications, timezone.now())

    with transaction.atomic():
        snapshot = Snapshot.objects.create(
            code=quote.code,
            total_value=quote.total_value,
            contract_to=config.contract_to,
            contract_instructions=config.contract_instructions,
        )
        SnapshotItem.objects.bulk_create(
            [
                SnapshotItem(
                    snapshot=snapshot,
                    type_id=line.type_id,
                    type_name=line.type_name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    percent_applied=line.percent_applied,
                    price_source=line.price_source,
                    line_total=line.line_total,
                    is_flagged=line.is_flagged,
                    flag_reason=line.flag_reason,
                )
                for line in quote.lines
            ]
        )
    return snapshot
