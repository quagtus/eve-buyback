"""Rule summary: every configured rule in one auditable list.

Django admin's per-model list views cannot show how rules interact, which is
exactly what matters when three rules touch the same item. This page sorts by
match level so the winning rule is obvious.
"""

from datetime import datetime

from django.shortcuts import render

from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule

LEVEL_ORDER = {"Type": 0, "Group": 1, "Category": 2}

# Icon key per rule kind, resolved to an inline SVG in the template. Kept as
# a stable slug rather than markup so the view stays presentation-agnostic.
KIND_ICONS = {
    "Blacklist": "ban",
    "Sale": "tag",
    "Custom rule": "sliders",
    "Category default": "layers",
}


def _targets(instance):
    """One row per match level the rule actually targets."""
    for level, manager in (
        ("Type", instance.types),
        ("Group", instance.groups),
        ("Category", instance.categories),
    ):
        names = [str(obj) for obj in manager.all()]
        if names:
            yield level, names


def _sale_status(sale, now: datetime) -> str:
    if now < sale.valid_from:
        return "scheduled"
    if now > sale.valid_to:
        return "expired"
    return "active"


def build_summary_rows(now: datetime) -> list[dict]:
    rows: list[dict] = []

    for sale in SaleRule.objects.prefetch_related("categories", "groups", "types"):
        for level, names in _targets(sale):
            rows.append({
                "kind": "Sale",
                "label": sale.label,
                "level": level,
                "targets": names,
                "percent": sale.percent,
                "status": _sale_status(sale, now),
                "window": f"{sale.valid_from:%Y-%m-%d} to {sale.valid_to:%Y-%m-%d}",
            })

    for rule in CustomRule.objects.prefetch_related("categories", "groups", "types"):
        for level, names in _targets(rule):
            rows.append({
                "kind": "Custom rule",
                "label": rule.label,
                "level": level,
                "targets": names,
                "percent": rule.percent,
                "status": "active",
                "window": "",
            })

    for default in CategoryDefaultPercent.objects.select_related("category"):
        rows.append({
            "kind": "Category default",
            "label": default.category.name,
            "level": "Category",
            "targets": [default.category.name],
            "percent": default.percent,
            "status": "active",
            "window": "",
        })

    for entry in BlacklistEntry.objects.select_related("category", "group", "type"):
        target = entry.category or entry.group or entry.type
        level = "Category" if entry.category_id else ("Group" if entry.group_id else "Type")
        rows.append({
            "kind": "Blacklist",
            "label": str(target),
            "level": level,
            "targets": [str(target)],
            "percent": None,
            "status": "active",
            "window": "",
        })

    for row in rows:
        row["icon"] = KIND_ICONS[row["kind"]]

    kind_order = {"Blacklist": 0, "Sale": 1, "Custom rule": 2, "Category default": 3}
    rows.sort(key=lambda r: (kind_order[r["kind"]], LEVEL_ORDER[r["level"]], r["label"]))
    return rows


def rule_summary(request):
    from django.utils import timezone

    return render(
        request,
        "pricing/rule_summary.html",
        {
            "rows": build_summary_rows(timezone.now()),
            "title": "Rule summary",
        },
    )
