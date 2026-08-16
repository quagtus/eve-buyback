"""Translate Django rule models into the frozen domain RuleSet.

Loaded once per quote so resolution never touches the ORM per item.
"""

from pricing.domain.ruleset import Rule, RuleSet
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule


def _to_rule(instance, *, with_window: bool) -> Rule:
    return Rule(
        label=instance.label,
        percent=instance.percent,
        category_ids=frozenset(c.id for c in instance.categories.all()),
        group_ids=frozenset(g.id for g in instance.groups.all()),
        type_ids=frozenset(t.id for t in instance.types.all()),
        valid_from=getattr(instance, "valid_from", None) if with_window else None,
        valid_to=getattr(instance, "valid_to", None) if with_window else None,
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
        sales=tuple(_to_rule(rule, with_window=True) for rule in sales),
        custom_rules=tuple(_to_rule(rule, with_window=False) for rule in custom),
        category_defaults={
            row.category_id: row.percent
            for row in CategoryDefaultPercent.objects.all()
        },
    )
