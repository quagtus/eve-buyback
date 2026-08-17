"""Deployment settings that only bite in production.

CSRF_TRUSTED_ORIGINS is the classic one: everything works on localhost, then
every POST fails with "Origin checking failed" the moment the app is served
from a real domain behind TLS.
"""

import pytest
from django.test import Client
from django.test.utils import override_settings

DOMAIN = "buyback.example.test"
TRUSTED = f"https://{DOMAIN}"


def test_csv_env_drops_blanks_and_whitespace():
    """A trailing comma or stray space must not become an empty origin.

    An empty string in CSRF_TRUSTED_ORIGINS matches nothing and is easy to
    introduce by hand-editing a .env.
    """
    import os

    from config.settings import _csv_env

    os.environ["_TEST_CSV"] = " https://a.example.com , ,https://b.example.com,"
    try:
        assert _csv_env("_TEST_CSV") == ["https://a.example.com", "https://b.example.com"]
    finally:
        del os.environ["_TEST_CSV"]


def test_csv_env_returns_empty_list_when_unset():
    from config.settings import _csv_env

    assert _csv_env("_DEFINITELY_NOT_SET_12345") == []


def _client_with_token():
    """A client holding a real CSRF token, so only the Origin check varies.

    The default test client sets enforce_csrf_checks=False and skips CSRF
    entirely — any assertion about it would pass for the wrong reason. And a
    POST with no token is rejected regardless of Origin, which would make the
    trusted/untrusted comparison meaningless. So: enforce checks, then fetch a
    genuine token first.
    """
    client = Client(enforce_csrf_checks=True)
    client.get("/", HTTP_HOST=DOMAIN, secure=True)
    return client, client.cookies["csrftoken"].value


# A cross-origin POST is the only case CSRF_TRUSTED_ORIGINS actually governs.
# Django allows a same-origin POST (Origin == Host) without consulting the
# setting at all, so testing with a matching Origin passes even when the list
# is empty — proving nothing. www.<domain> is a different origin from <domain>.
CROSS_ORIGIN = f"https://www.{DOMAIN}"


@pytest.mark.django_db
def test_cross_origin_post_is_allowed_when_the_origin_is_trusted():
    """The deploy regression: POSTs rejected with 'Origin checking failed'."""
    with override_settings(ALLOWED_HOSTS=[DOMAIN], CSRF_TRUSTED_ORIGINS=[CROSS_ORIGIN]):
        client, token = _client_with_token()
        response = client.post(
            "/submit/",
            {"raw_text": "", "csrfmiddlewaretoken": token},
            HTTP_HOST=DOMAIN,
            HTTP_ORIGIN=CROSS_ORIGIN,
            secure=True,
        )

    assert response.status_code != 403, (
        "a POST from a configured trusted origin was rejected — "
        "CSRF_TRUSTED_ORIGINS is not being applied"
    )


@pytest.mark.django_db
def test_same_cross_origin_post_is_rejected_when_the_list_is_empty():
    """Pairs with the test above: the difference must be the setting itself."""
    with override_settings(ALLOWED_HOSTS=[DOMAIN], CSRF_TRUSTED_ORIGINS=[]):
        client, token = _client_with_token()
        response = client.post(
            "/submit/",
            {"raw_text": "", "csrfmiddlewaretoken": token},
            HTTP_HOST=DOMAIN,
            HTTP_ORIGIN=CROSS_ORIGIN,
            secure=True,
        )

    assert response.status_code == 403


@pytest.mark.django_db
def test_post_from_an_untrusted_origin_is_still_rejected():
    """The fix must not be so permissive that it stops protecting anything."""
    with override_settings(ALLOWED_HOSTS=[DOMAIN], CSRF_TRUSTED_ORIGINS=[TRUSTED]):
        client, token = _client_with_token()
        response = client.post(
            "/submit/",
            {"raw_text": "", "csrfmiddlewaretoken": token},
            HTTP_HOST=DOMAIN,
            HTTP_ORIGIN="https://attacker.example.test",
            secure=True,
        )

    assert response.status_code == 403, "an untrusted origin was accepted"


@pytest.mark.django_db
def test_untrusted_origin_is_rejected_even_when_the_list_is_empty():
    """Guards the default: no configured origins must not mean 'allow all'."""
    with override_settings(ALLOWED_HOSTS=[DOMAIN], CSRF_TRUSTED_ORIGINS=[]):
        client, token = _client_with_token()
        response = client.post(
            "/submit/",
            {"raw_text": "", "csrfmiddlewaretoken": token},
            HTTP_HOST=DOMAIN,
            HTTP_ORIGIN="https://attacker.example.test",
            secure=True,
        )

    assert response.status_code == 403


def test_secure_cookie_flags_are_opt_in():
    """Marking cookies Secure over plain HTTP makes them undeliverable.

    Defaulting these on would lock a developer out of the admin on localhost.
    """
    from django.conf import settings

    assert settings.SESSION_COOKIE_SECURE is False
    assert settings.CSRF_COOKIE_SECURE is False


def test_proxy_ssl_header_is_not_set_by_default():
    """Trusting X-Forwarded-Proto when no proxy exists lets a client forge it."""
    from django.conf import settings

    assert getattr(settings, "SECURE_PROXY_SSL_HEADER", None) is None
