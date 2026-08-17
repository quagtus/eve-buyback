from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from catalog.models import EveCategory, EveGroup, EveType

PERCENT_VALIDATORS = [
    MinValueValidator(Decimal("0")),
    MaxValueValidator(Decimal("1000")),
]


class CategoryDefaultPercent(models.Model):
    """Base buyback rate for an EVE category. 80.00 means 80%."""

    category = models.OneToOneField(
        EveCategory, on_delete=models.CASCADE, related_name="default_percent"
    )
    percent = models.DecimalField(
        max_digits=6, decimal_places=2, validators=PERCENT_VALIDATORS
    )

    class Meta:
        ordering = ["category__name"]

    def __str__(self):
        return f"{self.category.name}: {self.percent}%"


class TargetedRule(models.Model):
    """Shared shape for rules that target any mix of categories/groups/types.

    Percentages live on the concrete subclasses rather than here: ReprocessingRule
    shares the targeting but carries a yield rate instead, and a `percent` column
    it never uses would invite the two to be confused.
    """

    label = models.CharField(max_length=120)
    categories = models.ManyToManyField(EveCategory, blank=True)
    groups = models.ManyToManyField(EveGroup, blank=True)
    types = models.ManyToManyField(EveType, blank=True)

    class Meta:
        abstract = True
        ordering = ["label"]

    def __str__(self):
        return self.label


class CustomRule(TargetedRule):
    """Always-on percentage override. Beaten only by sales and the blacklist."""

    percent = models.DecimalField(
        max_digits=6, decimal_places=2, validators=PERCENT_VALIDATORS
    )

    def __str__(self):
        return f"{self.label} ({self.percent}%)"


class SaleRule(TargetedRule):
    """Time-boxed percentage that outranks custom rules while active."""

    percent = models.DecimalField(
        max_digits=6, decimal_places=2, validators=PERCENT_VALIDATORS
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()

    class Meta(TargetedRule.Meta):
        abstract = False
        ordering = ["-valid_from"]

    def clean(self):
        super().clean()
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValidationError({"valid_to": "End must not precede start."})

    def __str__(self):
        return f"{self.label} ({self.percent}%)"


YIELD_VALIDATORS = [
    MinValueValidator(Decimal("0")),
    MaxValueValidator(Decimal("1")),
]


class ReprocessingRule(TargetedRule):
    """Price matched items from their reprocessing outputs, not their own price.

    yield_rate is a fraction: 0.9063 means 90.63% recovery. It is capped at 1
    because reprocessing cannot return more than the material content, and a
    value entered as 90.63 rather than 0.9063 would otherwise inflate every ore
    quote by a hundredfold.
    """

    yield_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=YIELD_VALIDATORS,
        help_text="Recovery fraction, e.g. 0.9063 for 90.63%. Ore and ice use "
        "different reprocessing skills, so they usually need separate rules.",
    )

    def __str__(self):
        return f"{self.label} (yield {self.yield_rate})"


class BlacklistEntry(models.Model):
    """One banned category, group, or type. Exactly one target must be set."""

    category = models.ForeignKey(
        EveCategory, null=True, blank=True, on_delete=models.CASCADE
    )
    group = models.ForeignKey(
        EveGroup, null=True, blank=True, on_delete=models.CASCADE
    )
    type = models.ForeignKey(
        EveType, null=True, blank=True, on_delete=models.CASCADE
    )

    class Meta:
        verbose_name_plural = "blacklist entries"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(category__isnull=False, group__isnull=True, type__isnull=True)
                    | models.Q(category__isnull=True, group__isnull=False, type__isnull=True)
                    | models.Q(category__isnull=True, group__isnull=True, type__isnull=False)
                ),
                name="blacklist_entry_exactly_one_target",
            )
        ]

    def clean(self):
        super().clean()
        targets = [self.category_id, self.group_id, self.type_id]
        if sum(target is not None for target in targets) != 1:
            raise ValidationError("Set exactly one of category, group, or type.")

    def __str__(self):
        target = self.category or self.group or self.type
        return f"Blacklisted: {target}"
