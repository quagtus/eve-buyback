"""Application layer: orchestrates gateway, rules, and persistence."""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from buyback.domain.gateway import PriceAppraisalGateway
from buyback.domain.quote import build_quote
from buyback.infrastructure.janice import JaniceAppraisalGateway
from buyback.models import Quote, QuoteItem
from catalog.models import EveType
from pricing.domain.ruleset import ItemClassification
from pricing.repositories import load_ruleset
from siteconfig.models import SiteConfig


class EmptyAppraisalError(RuntimeError):
    """Nothing in the paste could be priced, so there is nothing to quote."""


class DuplicateQuoteError(RuntimeError):
    """A quote with this Janice code already exists."""


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


def generate_quote(
    raw_text: str, gateway: PriceAppraisalGateway | None = None
) -> Quote:
    config = SiteConfig.load()
    gateway = gateway or build_default_gateway(config)

    appraisal = gateway.create_appraisal(raw_text)
    if not appraisal.has_items:
        raise EmptyAppraisalError("Janice could not price any item in that list.")

    ruleset = load_ruleset()
    classifications = _classifications({item.type_id for item in appraisal.items})
    quote = build_quote(appraisal, ruleset, classifications, timezone.now())

    # The IntegrityError must be caught OUTSIDE the atomic block: Django
    # marks an atomic block's transaction as broken the instant an exception
    # escapes it, so catching inside and continuing to use the same
    # transaction would raise TransactionManagementError instead. Letting it
    # propagate past the `with` first, then catching it here, closes the
    # broken transaction cleanly before we raise the domain-level error.
    try:
        with transaction.atomic():
            quote = Quote.objects.create(
                code=quote.code,
                total_value=quote.total_value,
                contract_to=config.contract_to,
                contract_instructions=config.contract_instructions,
            )
            QuoteItem.objects.bulk_create(
                [
                    QuoteItem(
                        quote=quote,
                        type_id=line.type_id,
                        type_name=line.type_name,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                        percent_applied=line.percent_applied,
                        price_source_kind=line.price_source_kind,
                        price_source_label=line.price_source_label,
                        line_total=line.line_total,
                        is_flagged=line.is_flagged,
                        flag_reason_code=line.flag_reason.value if line.flag_reason else None,
                    )
                    for line in quote.lines
                ]
            )
    except IntegrityError as exc:
        raise DuplicateQuoteError(
            f"A quote with code {quote.code!r} already exists."
        ) from exc
    return quote
