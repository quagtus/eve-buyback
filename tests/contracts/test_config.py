"""The page must tell the operator exactly which env vars are unset.

An ESI integration with a missing client id fails deep inside an HTTP call with
an opaque message; naming the gap up front is the difference between a two-minute
fix and an hour of guessing.
"""

from django.test.utils import override_settings

from contracts.infrastructure.config import REQUIRED_SETTINGS, missing_esi_settings

COMPLETE = {
    "ESI_CLIENT_ID": "client-id",
    "ESI_CLIENT_SECRET": "client-secret",
    "ESI_CALLBACK_URL": "https://buyback.example.test/admin/contracts/callback/",
    "ESI_TOKEN_KEY": "a-fernet-key",
}


def test_nothing_missing_when_every_required_setting_is_set():
    with override_settings(**COMPLETE):
        assert missing_esi_settings() == ()


def test_each_required_setting_is_reported_when_blank():
    """Blank, not just absent: an env var set to "" is the common real case."""
    for name in REQUIRED_SETTINGS:
        with override_settings(**{**COMPLETE, name: ""}):
            assert missing_esi_settings() == (name,)


def test_all_missing_settings_are_reported_together():
    blank = {name: "" for name in REQUIRED_SETTINGS}
    with override_settings(**blank):
        assert set(missing_esi_settings()) == set(REQUIRED_SETTINGS)


def test_user_agent_is_not_required():
    """It has a default, so a deployment without it still works."""
    assert "ESI_USER_AGENT" not in REQUIRED_SETTINGS
