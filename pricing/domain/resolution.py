"""Resolve one item to a buyback percentage.

Tiers are absolute and evaluated in order:
    1. Blacklist        (0%, flagged — beats everything, including sales)
    2. Active sale
    3. Custom rule
    4. Category default
    5. Nothing configured (0%, flagged)

Specificity (Type > Group > Category) only breaks ties *within* tier 2 and
tier 3. It never promotes a rule across tiers, which is what "a sale always
wins" means.
"""

from datetime import datetime
from decimal import Decimal

from pricing.domain.decisions import PriceDecision, PriceSourceKind
from pricing.domain.ruleset import ItemClassification, Rule, RuleSet

ZERO = Decimal("0")


def _best_match(rules: tuple[Rule, ...], item: ItemClassification) -> Rule | None:
    """Return the rule matching `item` at the most specific level, or None.

    Specificity is absolute: a higher match level always wins regardless of
    percent. Only when two rules match at the *same* level does percent come
    into play, as a deterministic tie-break — the highest percent wins.

    That same-level tie is a defensive backstop, not the primary conflict
    policy. Overlapping same-level rules are supposed to be impossible: the
    admin form blocks them via `find_conflicts`. But that guard only exists
    at the form layer, so direct ORM writes (a shell script, a data
    migration, a fixture load) can still produce two same-level matches. If
    that ever happens, iteration order must not silently decide the price —
    it would otherwise reflect Django `Meta.ordering` clauses written for
    admin list display (e.g. `["-valid_from"]`), not pricing, and could quote
    the seller a worse price than the data actually allows. Honouring the
    higher percent is the defensible business behaviour for a buyback in
    that broken-data state: the seller gets the better of the two offers
    rather than an arbitrary one.
    """
    best: Rule | None = None
    best_level = None
    for rule in rules:
        level = rule.match_level(item)
        if level is None:
            continue
        if (
            best_level is None
            or level > best_level
            or (level == best_level and rule.percent > best.percent)
        ):
            best, best_level = rule, level
    return best


def resolve_price(
    item: ItemClassification, ruleset: RuleSet, now: datetime
) -> PriceDecision:
    if ruleset.is_blacklisted(item):
        return PriceDecision(
            percent=ZERO,
            source_kind=PriceSourceKind.BLACKLIST,
            source_label="Blacklisted",
            flagged=True,
            flag_reason="Blacklisted",
        )

    active_sales = tuple(rule for rule in ruleset.sales if rule.is_active(now))
    sale = _best_match(active_sales, item)
    if sale is not None:
        return PriceDecision(
            percent=sale.percent,
            source_kind=PriceSourceKind.SALE,
            source_label=sale.label,
        )

    custom = _best_match(ruleset.custom_rules, item)
    if custom is not None:
        return PriceDecision(
            percent=custom.percent,
            source_kind=PriceSourceKind.CUSTOM,
            source_label=custom.label,
        )

    default = ruleset.category_defaults.get(item.category_id)
    if default is not None:
        return PriceDecision(
            percent=default,
            source_kind=PriceSourceKind.CATEGORY_DEFAULT,
            source_label="Category default",
        )

    return PriceDecision(
        percent=ZERO,
        source_kind=PriceSourceKind.NONE,
        source_label="No rule configured",
        flagged=True,
        flag_reason="No rule configured",
    )
