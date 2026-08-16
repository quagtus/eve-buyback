"""Translate Django rule models into the frozen domain RuleSet.

Loaded once per quote so resolution never touches the ORM per item.
"""

from pricing.domain.ruleset import Rule, RuleSet
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule


def to_domain_rule(instance) -> Rule:
    """Map a CustomRule or SaleRule model instance to a domain Rule.

    `getattr(..., "valid_from", None)` already yields None for CustomRule,
    which has no such field, so a rule with no window is naturally "always
    active" — the correct semantics for a custom rule — without needing a
    separate flag to suppress it.
    """
    return Rule(
        label=instance.label,
        percent=instance.percent,
        category_ids=frozenset(c.id for c in instance.categories.all()),
        group_ids=frozenset(g.id for g in instance.groups.all()),
        type_ids=frozenset(t.id for t in instance.types.all()),
        valid_from=getattr(instance, "valid_from", None),
        valid_to=getattr(instance, "valid_to", None),
    )


def load_ruleset() -> RuleSet:
    entries = list(BlacklistEntry.objects.all())

    custom = CustomRule.objects.prefetch_related("categories", "groups", "types")
    sales = SaleRule.objects.prefetch_related("categories", "groups", "types")

    return RuleSet(
        blacklist_category_ids=frozenset(
            e.category_id for e in entries if e.category_id is not None
        ),
        blacklist_group_ids=frozenset(
            e.group_id for e in entries if e.group_id is not None
        ),
        blacklist_type_ids=frozenset(
            e.type_id for e in entries if e.type_id is not None
        ),
        sales=tuple(to_domain_rule(rule) for rule in sales),
        custom_rules=tuple(to_domain_rule(rule) for rule in custom),
        category_defaults={
            row.category_id: row.percent
            for row in CategoryDefaultPercent.objects.all()
        },
    )
