from django.db import models
from django.utils import timezone


class EsiCharacter(models.Model):
    """The single authenticated character whose contracts get checked.

    Singleton on pk=1, following SiteConfig: linking a different character
    replaces this row, which is the whole intent — the operator checks their own
    pending contracts, and checking somebody else's means logging in as them.

    character_id is a plain field rather than the primary key precisely because
    it changes when that happens.
    """

    character_id = models.BigIntegerField()
    character_name = models.CharField(max_length=255)
    refresh_token_ciphertext = models.TextField(
        blank=True,
        help_text="Fernet ciphertext. Cleared on disconnect; never stored in plain text.",
    )
    scopes = models.TextField(
        blank=True, help_text="Space-separated, as SSO returns them."
    )
    linked_at = models.DateTimeField(default=timezone.now)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "ESI character"
        verbose_name_plural = "ESI character"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @property
    def is_connected(self) -> bool:
        return bool(self.refresh_token_ciphertext)

    def disconnect(self, reason: str = "") -> None:
        """Drop the credential, keep the row so the page can explain itself."""
        self.refresh_token_ciphertext = ""
        self.last_error = reason[:255]
        self.save(update_fields=["refresh_token_ciphertext", "last_error"])

    @classmethod
    def current(cls) -> "EsiCharacter | None":
        return cls.objects.filter(pk=1).first()

    def __str__(self):
        return self.character_name or "no character linked"
