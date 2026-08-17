"""Render stored machine keys as translated text.

This is the ONLY place keys become human-readable. The rule that matters:
a rule's name is the operator's data and is printed verbatim, while a
system source kind is buyback's own UI text and is translated. Item names
come from EVE via Janice and are never touched here at all.
"""

from django import template
from django.utils.translation import gettext_lazy as _

register = template.Library()

NO_LABEL = "—"

SOURCE_KIND_LABELS = {
    "BLACKLIST": _("Blacklisted"),
    "CATEGORY_DEFAULT": _("Category default"),
    "NONE": NO_LABEL,
}

FLAG_REASON_LABELS = {
    "BLACKLISTED": _("Blacklisted"),
    "NO_RULE": _("No rule configured"),
    "UNRECOGNIZED": _("Unrecognized item"),
    "UNPARSEABLE": _("Could not be parsed"),
    "BELOW_PORTION_SIZE": _("Less than one reprocessing batch"),
    "ZERO_YIELD": _("Reprocessing yield is zero"),
}

# Kinds whose display value is the admin-authored rule name, not a translation.
# REPROCESSED belongs here rather than in SOURCE_KIND_LABELS: a reprocessed line
# has a rule behind it, and showing the translated word "Reprocessed" instead
# would throw away which rule was responsible.
NAMED_KINDS = frozenset({"CUSTOM", "SALE", "REPROCESSED"})


@register.filter
def price_source_label(item) -> str:
    kind = getattr(item, "price_source_kind", "") or ""
    if kind in NAMED_KINDS:
        return getattr(item, "price_source_label", "") or NO_LABEL
    return str(SOURCE_KIND_LABELS.get(kind, NO_LABEL))


@register.filter
def flag_reason_label(item) -> str:
    code = getattr(item, "flag_reason_code", None)
    if not code:
        return ""
    return str(FLAG_REASON_LABELS.get(code, ""))
