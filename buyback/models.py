from django.db import models


class Snapshot(models.Model):
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

    class Meta:
        ordering = ["-created_at"]

    @property
    def item_count(self) -> int:
        return self.items.count()

    @property
    def janice_url(self) -> str:
        return f"https://janice.e-351.com/a/{self.code}"

    def __str__(self):
        return f"{self.code} ({self.total_value} ISK)"


class SnapshotItem(models.Model):
    """One frozen line of a snapshot.

    type_id is nullable because unparseable paste lines are preserved as
    flagged zero-value rows so the seller can see exactly what was rejected.
    """

    snapshot = models.ForeignKey(
        Snapshot, on_delete=models.CASCADE, related_name="items"
    )
    type_id = models.BigIntegerField(null=True, blank=True)
    type_name = models.CharField(max_length=255)
    quantity = models.BigIntegerField()
    unit_price = models.DecimalField(max_digits=20, decimal_places=2)
    percent_applied = models.DecimalField(max_digits=6, decimal_places=2)
    price_source = models.CharField(max_length=120)
    line_total = models.DecimalField(max_digits=20, decimal_places=2)
    is_flagged = models.BooleanField(default=False)
    flag_reason = models.CharField(max_length=120, null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.type_name} x{self.quantity}"
