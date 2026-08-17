"""Application layer: orchestrates gateway, rules, and persistence."""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from buyback.domain.gateway import PriceAppraisalGateway
from buyback.domain.quote import build_quote
from buyback.infrastructure.janice import JaniceAppraisalGateway
from buyback.models import Quote, QuoteItem, QuoteItemMaterial
from catalog.models import EveType, EveTypeMaterial
from pricing.domain.reprocessing import MaterialYield
from pricing.domain.resolution import resolve_reprocessing
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


def _reprocessing_inputs(appraisal, ruleset, classifications):
    """Yields, portion sizes and names for every appraised item that reprocesses.

    Returns empty mappings when no reprocessing rule matches, which is what keeps
    an ordinary paste from paying for an extra Janice call.
    """
    reprocessed_type_ids = [
        item.type_id
        for item in appraisal.items
        if item.type_id in classifications
        and resolve_reprocessing(classifications[item.type_id], ruleset) is not None
    ]
    if not reprocessed_type_ids:
        return {}, {}, {}

    portion_sizes = dict(
        EveType.objects.filter(id__in=reprocessed_type_ids).values_list(
            "id", "portion_size"
        )
    )

    yields: dict[int, list[MaterialYield]] = {}
    names: dict[int, str] = {}
    rows = EveTypeMaterial.objects.filter(
        type_id__in=reprocessed_type_ids
    ).select_related("material")
    for row in rows:
        yields.setdefault(row.type_id, []).append(
            MaterialYield(type_id=row.material_id, quantity_per_batch=row.quantity)
        )
        names[row.material_id] = row.material.name

    return (
        {type_id: tuple(items) for type_id, items in yields.items()},
        portion_sizes,
        names,
    )


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

    material_yields, portion_sizes, material_names = _reprocessing_inputs(
        appraisal, ruleset, classifications
    )

    # One call for every distinct output material, and only when something
    # actually reprocesses. Outside any atomic block, like the appraisal call:
    # holding a transaction open across a 30-second HTTP request is the mistake
    # already fixed below.
    material_prices = {}
    material_type_ids = {
        output.type_id for outputs in material_yields.values() for output in outputs
    }
    if material_type_ids:
        material_prices = gateway.price_types(material_type_ids)

    quote_record = build_quote(
        appraisal,
        ruleset,
        {**classifications, **_classifications(material_type_ids)},
        timezone.now(),
        material_yields=material_yields,
        portion_sizes=portion_sizes,
        material_prices=material_prices,
        material_names=material_names,
    )

    # The IntegrityError must be caught OUTSIDE the atomic block: Django
    # marks an atomic block's transaction as broken the instant an exception
    # escapes it, so catching inside and continuing to use the same
    # transaction would raise TransactionManagementError instead. Letting it
    # propagate past the `with` first, then catching it here, closes the
    # broken transaction cleanly before we raise the domain-level error.
    try:
        with transaction.atomic():
            quote = Quote.objects.create(
                code=quote_record.code,
                total_value=quote_record.total_value,
                contract_to=config.contract_to,
                contract_instructions=config.contract_instructions,
                contract_station=config.contract_station,
                contract_days=config.contract_default_days,
            )
            created_items = QuoteItem.objects.bulk_create(
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
                        yield_rate_applied=line.yield_rate_applied,
                        portion_size_applied=line.portion_size_applied,
                    )
                    for line in quote_record.lines
                ]
            )
            # bulk_create returns the instances with primary keys populated on
            # PostgreSQL, in the order given, so zipping back to the domain
            # lines pairs each stored row with the line it came from.
            QuoteItemMaterial.objects.bulk_create(
                [
                    QuoteItemMaterial(
                        quote_item=created,
                        type_id=material.type_id,
                        type_name=material.type_name,
                        quantity=material.quantity,
                        unit_price=material.unit_price,
                        percent_applied=material.percent_applied,
                        line_total=material.line_total,
                        is_unpriced=material.is_unpriced,
                    )
                    for created, line in zip(created_items, quote_record.lines)
                    for material in line.materials
                ]
            )
    except IntegrityError as exc:
        raise DuplicateQuoteError(
            f"A quote with code {quote_record.code!r} already exists."
        ) from exc
    return quote
