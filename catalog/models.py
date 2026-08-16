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

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
