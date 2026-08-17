"""The admin page: auth, OAuth state handling, and the rendered states.

Every failure mode here must render a panel. A 500 on a page whose entire job is
to report on an external service would be self-defeating.
"""

import pytest
from cryptography.fernet import Fernet
from django.test.utils import override_settings

from contracts.models import EsiCharacter
from contracts.views import STATE_SESSION_KEY, VERIFIER_SESSION_KEY

CHECK_URL = "/admin/contracts/check/"
LINK_URL = "/admin/contracts/link/"
CALLBACK_URL = "/admin/contracts/callback/"
DISCONNECT_URL = "/admin/contracts/disconnect/"

CONFIGURED = {
    "ESI_CLIENT_ID": "client-id",
    "ESI_CLIENT_SECRET": "client-secret",
    "ESI_CALLBACK_URL": "https://buyback.example.test" + CALLBACK_URL,
    "ESI_TOKEN_KEY": Fernet.generate_key().decode(),
}


@pytest.fixture
def admin_client_logged_in(client, django_user_model, db):
    django_user_model.objects.create_superuser(
        "esiadmin", "esi@example.com", "pw12345678"
    )
    client.login(username="esiadmin", password="pw12345678")
    return client


@pytest.mark.django_db
def test_the_check_page_requires_a_staff_login(client):
    for url in (CHECK_URL, LINK_URL, CALLBACK_URL, DISCONNECT_URL):
        assert client.get(url).status_code in (302, 403), url


@pytest.mark.django_db
def test_an_unconfigured_deployment_names_the_missing_settings(admin_client_logged_in):
    """Not a 500, and not a vague "ESI unavailable"."""
    with override_settings(**{name: "" for name in CONFIGURED}):
        response = admin_client_logged_in.get(CHECK_URL)

    assert response.status_code == 200
    body = response.content.decode()
    assert "ESI_CLIENT_ID" in body
    assert "ESI_TOKEN_KEY" in body


@pytest.mark.django_db
def test_a_configured_deployment_with_no_character_offers_to_connect(
    admin_client_logged_in,
):
    with override_settings(**CONFIGURED):
        response = admin_client_logged_in.get(CHECK_URL)

    assert response.status_code == 200
    assert LINK_URL in response.content.decode()


@pytest.mark.django_db
def test_link_redirects_to_sso_and_stores_state_and_verifier(admin_client_logged_in):
    with override_settings(**CONFIGURED):
        response = admin_client_logged_in.get(LINK_URL)

    assert response.status_code == 302
    assert response["Location"].startswith(
        "https://login.eveonline.com/v2/oauth/authorize?"
    )
    assert admin_client_logged_in.session[STATE_SESSION_KEY]
    assert admin_client_logged_in.session[VERIFIER_SESSION_KEY]


@pytest.mark.django_db
def test_link_does_nothing_when_the_app_is_not_configured(admin_client_logged_in):
    with override_settings(**{name: "" for name in CONFIGURED}):
        response = admin_client_logged_in.get(LINK_URL)

    assert response.status_code == 302
    assert response["Location"] == CHECK_URL
    assert STATE_SESSION_KEY not in admin_client_logged_in.session


@pytest.mark.django_db
def test_a_callback_with_a_mismatched_state_is_rejected(admin_client_logged_in):
    """The CSRF defence for the OAuth round trip."""
    session = admin_client_logged_in.session
    session[STATE_SESSION_KEY] = "the-real-state"
    session[VERIFIER_SESSION_KEY] = "verifier"
    session.save()

    with override_settings(**CONFIGURED):
        response = admin_client_logged_in.get(
            CALLBACK_URL, {"state": "forged", "code": "whatever"}
        )

    assert response.status_code == 302
    assert EsiCharacter.current() is None


@pytest.mark.django_db
def test_a_callback_with_no_state_in_the_session_is_rejected(admin_client_logged_in):
    with override_settings(**CONFIGURED):
        response = admin_client_logged_in.get(
            CALLBACK_URL, {"state": "anything", "code": "whatever"}
        )

    assert response.status_code == 302
    assert EsiCharacter.current() is None


@pytest.mark.django_db
def test_the_state_is_single_use(admin_client_logged_in):
    """A replayed callback must not be accepted a second time."""
    session = admin_client_logged_in.session
    session[STATE_SESSION_KEY] = "state-1"
    session[VERIFIER_SESSION_KEY] = "verifier"
    session.save()

    with override_settings(**CONFIGURED):
        admin_client_logged_in.get(CALLBACK_URL, {"state": "state-1", "code": "bad"})

    assert STATE_SESSION_KEY not in admin_client_logged_in.session


@pytest.mark.django_db
def test_a_callback_carrying_an_sso_error_is_reported(admin_client_logged_in):
    session = admin_client_logged_in.session
    session[STATE_SESSION_KEY] = "state-1"
    session[VERIFIER_SESSION_KEY] = "verifier"
    session.save()

    with override_settings(**CONFIGURED):
        response = admin_client_logged_in.get(
            CALLBACK_URL, {"state": "state-1", "error": "access_denied"}
        )

    assert response.status_code == 302
    assert EsiCharacter.current() is None


@pytest.mark.django_db
def test_disconnect_clears_the_credential(admin_client_logged_in):
    EsiCharacter.objects.create(
        character_id=1111, character_name="Operator", refresh_token_ciphertext="cipher"
    )

    with override_settings(**CONFIGURED):
        response = admin_client_logged_in.post(DISCONNECT_URL)

    assert response.status_code == 302
    assert EsiCharacter.current().is_connected is False


@pytest.mark.django_db
def test_disconnect_ignores_a_get(admin_client_logged_in):
    """State-changing actions do not happen on a GET."""
    EsiCharacter.objects.create(
        character_id=1111, character_name="Operator", refresh_token_ciphertext="cipher"
    )

    with override_settings(**CONFIGURED):
        admin_client_logged_in.get(DISCONNECT_URL)

    assert EsiCharacter.current().is_connected is True


@pytest.mark.django_db
def test_the_page_defines_dark_mode_colours(admin_client_logged_in):
    """Unfold sets html.dark for an explicit dark choice and for auto plus an
    OS preference. The rule summary page shipped hardcoded light values once and
    was unreadable."""
    with override_settings(**CONFIGURED):
        body = admin_client_logged_in.get(CHECK_URL).content.decode()

    assert "html.dark .cc" in body


@pytest.mark.django_db
def test_a_check_without_a_linked_character_does_not_error(admin_client_logged_in):
    with override_settings(**CONFIGURED):
        response = admin_client_logged_in.post(CHECK_URL)

    assert response.status_code == 200
    assert LINK_URL in response.content.decode()


@pytest.mark.django_db
def test_the_page_renders_the_admin_sidebar(admin_client_logged_in):
    """A plain render() omits admin.site.each_context, and Unfold's sidebar
    silently disappears — leaving no navigation off the page."""
    with override_settings(**CONFIGURED):
        body = admin_client_logged_in.get(CHECK_URL).content.decode()

    assert "/admin/buyback/quote/" in body, "sidebar navigation is missing"
    assert "/admin/pricing/summary/" in body
