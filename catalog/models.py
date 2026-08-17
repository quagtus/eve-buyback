from django.db import models


class EveCategory(models.Model):
    """Top-level EVE item category, e.g. Ship. PK is EVE's category_id."""

    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255, db_index=True)

    class Meta:
        verbose_name_plural = "EVE categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class EveGroup(models.Model):
    """EVE item group, e.g. Battleship. PK is EVE's group_id."""

    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255, db_index=True)
    category = models.ForeignKey(
        EveCategory, on_delete=models.CASCADE, related_name="groups"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class EveType(models.Model):
    """Concrete EVE item type, e.g. Raven. PK is EVE's type_id."""

    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255, db_index=True)
    group = models.ForeignKey(
        EveGroup, on_delete=models.CASCADE, related_name="types"
    )
    portion_size = models.PositiveIntegerField(
        default=1,
        help_text="Units consumed per reprocessing batch. 100 for raw ore, 1 for ice.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class EveTypeMaterial(models.Model):
    """What one reprocessing batch of `type` yields.

    quantity is per batch of `type.portion_size`, not per unit: Veldspar's
    portion_size is 100 and its Tritanium quantity is 400, so 100 units give 400.
    """

    type = models.ForeignKey(
        EveType, on_delete=models.CASCADE, related_name="materials"
    )
    material = models.ForeignKey(
        EveType, on_delete=models.CASCADE, related_name="reprocesses_from"
    )
    quantity = models.PositiveBigIntegerField()

    class Meta:
        ordering = ["type_id", "material_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["type", "material"], name="eve_type_material_unique"
            )
        ]

    def __str__(self):
        return f"{self.type} -> {self.quantity} x {self.material}"
