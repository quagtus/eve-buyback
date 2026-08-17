from django.db import models


class PricingBasis(models.TextChoices):
    """Maps to Janice's `pricing` query parameter."""

    BUY = "buy", "Buy price"
    SPLIT = "split", "Split price"
    SELL = "sell", "Sell price"


class PricingVariant(models.TextChoices):
    """Maps to Janice's `pricingVariant` query parameter."""

    IMMEDIATE = "immediate", "Immediate"
    TOP5PERCENT = "top5percent", "Top 5 percent"


class SiteConfigQuerySet(models.QuerySet):
    def delete(self):
        """Bulk deletion is blocked; the singleton must always exist."""
        return (0, {})


class SiteConfigManager(models.Manager.from_queryset(SiteConfigQuerySet)):
    pass


class SiteConfig(models.Model):
    """Admin-managed settings. Always exactly one row, pk=1.

    The Janice API key is deliberately NOT here — it is an environment
    variable, so the credential stays out of the database and its backups.
    """

    objects = SiteConfigManager()

    market_id = models.PositiveIntegerField(
        default=2, help_text="Janice market ID. 2 = Jita."
    )
    pricing_basis = models.CharField(
        max_length=16, choices=PricingBasis.choices, default=PricingBasis.SPLIT
    )
    pricing_variant = models.CharField(
        max_length=16,
        choices=PricingVariant.choices,
        default=PricingVariant.IMMEDIATE,
    )
    site_name = models.CharField(
            max_length=255,
            blank=True,
            help_text="Website name for the buyback.",
        )
    site_description = models.TextField(
        blank=True,
        help_text="Shown on the home page.",
    )
    site_footer = models.TextField(
        blank=True,
        help_text="Shown at the bottom of every page.",
    )
    site_logo = models.ImageField(
        blank=True,
        upload_to="",
        help_text="Shown on every page.",
    )
    contract_to = models.CharField(
        max_length=255,
        blank=True,
        help_text="Character or corporation that sellers should contract to.",
    )
    contract_default_days = models.PositiveIntegerField(
        default=3,
        help_text="Default number of days for the contract.",
    )
    contract_instructions = models.TextField(
        blank=True,
        help_text="Shown on every quote and frozen into each quote.",
    )
    contract_station = models.CharField(
        max_length=255,
        blank=True,
        help_text="Station where the contract should be delivered (frozen into each quote).",
    )

    class Meta:
        verbose_name = "site configuration"
        verbose_name_plural = "site configuration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """The singleton is never deleted."""
        return

    @classmethod
    def load(cls) -> "SiteConfig":
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def __str__(self):
        return "Site configuration"
