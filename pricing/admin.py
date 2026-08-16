from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin

from pricing.domain.overlap import find_conflicts
from pricing.domain.ruleset import Rule
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule


def _to_domain_rule(instance) -> Rule:
    return Rule(
        label=instance.label,
        percent=instance.percent,
        category_ids=frozenset(c.id for c in instance.categories.all()),
        group_ids=frozenset(g.id for g in instance.groups.all()),
        type_ids=frozenset(t.id for t in instance.types.all()),
        valid_from=getattr(instance, "valid_from", None),
        valid_to=getattr(instance, "valid_to", None),
    )


class TargetedRuleForm(forms.ModelForm):
    """Blocks rules that would make resolution ambiguous.

    Overlap is only a conflict at the same level: Ship 80% and Battleship 70%
    must coexist. Sales additionally only conflict when their windows intersect.
    """

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        candidate = Rule(
            label=cleaned.get("label") or "",
            percent=cleaned.get("percent") or 0,
            category_ids=frozenset(o.id for o in cleaned.get("categories", [])),
            group_ids=frozenset(o.id for o in cleaned.get("groups", [])),
            type_ids=frozenset(o.id for o in cleaned.get("types", [])),
            valid_from=cleaned.get("valid_from"),
            valid_to=cleaned.get("valid_to"),
        )

        others = self._meta.model.objects.prefetch_related(
            "categories", "groups", "types"
        )
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)

        conflicts = find_conflicts(candidate, [_to_domain_rule(o) for o in others])
        if conflicts:
            raise forms.ValidationError(
                "Overlaps existing rule(s) at the same level: "
                + ", ".join(conflicts)
                + ". Adjust the targets, or edit that rule instead."
            )
        return cleaned


class CustomRuleForm(TargetedRuleForm):
    class Meta:
        model = CustomRule
        fields = ["label", "percent", "categories", "groups", "types"]


class SaleRuleForm(TargetedRuleForm):
    class Meta:
        model = SaleRule
        fields = [
            "label",
            "percent",
            "categories",
            "groups",
            "types",
            "valid_from",
            "valid_to",
        ]


@admin.register(CategoryDefaultPercent)
class CategoryDefaultPercentAdmin(ModelAdmin):
    list_display = ["category", "percent"]
    list_select_related = ["category"]
    autocomplete_fields = ["category"]


@admin.register(CustomRule)
class CustomRuleAdmin(ModelAdmin):
    form = CustomRuleForm
    list_display = ["label", "percent"]
    search_fields = ["label"]
    autocomplete_fields = ["categories", "groups", "types"]


@admin.register(SaleRule)
class SaleRuleAdmin(ModelAdmin):
    form = SaleRuleForm
    list_display = ["label", "percent", "valid_from", "valid_to"]
    search_fields = ["label"]
    autocomplete_fields = ["categories", "groups", "types"]


@admin.register(BlacklistEntry)
class BlacklistEntryAdmin(ModelAdmin):
    list_display = ["__str__", "category", "group", "type"]
    autocomplete_fields = ["category", "group", "type"]
    list_select_related = ["category", "group", "type"]
