from datetime import timedelta

from django.db import models


class Quote(models.Model):
    """A permanent, frozen quote.

    The primary key IS the Janice appraisal code, so the same identifier
    resolves on this site and on janice.e-351.com/a/<code>. It is stored once,
    never duplicated into a second field.

    Every value here is resolved at generation time. Later edits to rules,
    blacklist entries, or site configuration must never alter an existing row.
    """

    code = models.CharField(primary_key=True, max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    total_value = models.DecimalField(max_digits=20, decimal_places=2)
    contract_to = models.CharField(max_length=255, blank=True)
    contract_instructions = models.TextField(blank=True)
    # Frozen alongside contract_to for the same reason: the quote page tells the
    # seller "this page is permanent and will not change", so every contract
    # instruction on it must be the one that applied when the quote was made.
    # Reading these live from SiteConfig would silently rewrite the terms of an
    # old quote when the operator moves station or changes the contract window.
    contract_station = models.CharField(max_length=255, blank=True)
    contract_days = models.PositiveIntegerField(default=3)

    class Meta:
        ordering = ["-created_at"]

    @property
    def item_count(self) -> int:
        return self.items.count()

    @property
    def janice_url(self) -> str:
        return f"https://janice.e-351.com/a/{self.code}"

    @property
    def contract_expires_at(self):
        """When a contract created at generation time would have expired.

        Computed rather than stored: it is a pure function of two frozen
        fields, so storing it would be a third copy of the same fact.
        """
        return self.created_at + timedelta(days=self.contract_days)

    def __str__(self):
        return f"{self.code} ({self.total_value} ISK)"


class QuoteItem(models.Model):
    """One frozen line of a quote.

    type_id is nullable because unparseable paste lines are preserved as
    flagged zero-value rows so the seller can see exactly what was rejected.
    """

    quote = models.ForeignKey(
        Quote, on_delete=models.CASCADE, related_name="items"
    )
    type_id = models.BigIntegerField(null=True, blank=True)
    type_name = models.CharField(max_length=255)
    quantity = models.BigIntegerField()
    unit_price = models.DecimalField(max_digits=20, decimal_places=2)
    percent_applied = models.DecimalField(max_digits=6, decimal_places=2)
    price_source_kind = models.CharField(
        max_length=32,
        help_text="Machine key for which category of rule won. Translated at render.",
    )
    price_source_label = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Admin-authored rule name. Never translated — it is data, not UI.",
    )
    line_total = models.DecimalField(max_digits=20, decimal_places=2)
    is_flagged = models.BooleanField(default=False)
    flag_reason_code = models.CharField(
        max_length=32, null=True, blank=True,
        help_text="Machine key for why the line was rejected. Translated at render.",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.type_name} x{self.quantity}"
