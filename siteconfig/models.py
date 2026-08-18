from django.core.files.uploadedfile import UploadedFile
from django.db import models

from siteconfig.images import process_logo


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
    # width_field/height_field let the template emit width= and height= without
    # opening the file on every page render, which reserves the header space and
    # stops it jumping as the image arrives.
    logo_width = models.PositiveIntegerField(null=True, blank=True, editable=False)
    logo_height = models.PositiveIntegerField(null=True, blank=True, editable=False)
    site_logo = models.ImageField(
        blank=True,
        upload_to="logos/",
        width_field="logo_width",
        height_field="logo_height",
        help_text=(
            "Shown in the header on every page. Resized to fit 512px on save, "
            "so a small file is fine — the original is not kept."
        ),
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

        # Captured before the write so the file being replaced can be removed
        # afterwards. ImageField deletes nothing on its own, so without this every
        # replacement leaves the previous logo on disk forever.
        previous = (
            type(self)
            .objects.filter(pk=1)
            .values_list("site_logo", flat=True)
            .first()
        )

        # Only a fresh upload is processed. Reprocessing on every save would
        # re-encode the JPEG each time, losing a little quality on every
        # unrelated settings edit.
        incoming = self.site_logo
        if incoming and isinstance(getattr(incoming, "file", None), UploadedFile):
            processed = process_logo(incoming.file)
            self.site_logo.save(processed.name, processed, save=False)

        super().save(*args, **kwargs)

        current = self.site_logo.name or ""
        if previous and previous != current:
            self._delete_stored_file(previous)

    @classmethod
    def _delete_stored_file(cls, name: str) -> None:
        """Remove a file the logo field no longer points at.

        Guarded by exists(): a missing file means someone cleaned up by hand, and
        that should not turn a settings save into an error.
        """
        storage = cls._meta.get_field("site_logo").storage
        if name and storage.exists(name):
            storage.delete(name)

    def delete(self, *args, **kwargs):
        """The singleton is never deleted."""
        return

    @classmethod
    def load(cls) -> "SiteConfig":
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def __str__(self):
        return "Site configuration"
