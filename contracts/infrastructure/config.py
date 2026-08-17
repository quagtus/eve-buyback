"""Which ESI settings a working integration needs.

Read through django.conf.settings rather than os.environ so override_settings
works in tests and so a deployment can set them any way Django supports.
"""

from django.conf import settings

REQUIRED_SETTINGS = (
    "ESI_CLIENT_ID",
    "ESI_CLIENT_SECRET",
    "ESI_CALLBACK_URL",
    "ESI_TOKEN_KEY",
)


def missing_esi_settings() -> tuple[str, ...]:
    """The required settings that are unset or blank, in declaration order."""
    return tuple(
        name for name in REQUIRED_SETTINGS if not getattr(settings, name, "")
    )
