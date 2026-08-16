import pytest
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import translation

TWO_LANGUAGES = [("en", "English"), ("eo", "Esperanto")]


@pytest.mark.django_db
def test_default_is_english_with_no_signal(client):
    """Assert the language that actually activated, not a defaulted header.

    An earlier version used response.headers.get("Content-Language", "en"),
    which passes even when LocaleMiddleware is removed entirely — the default
    masks the failure.
    """
    response = client.get(reverse("buyback:form"))

    assert response.status_code == 200
    assert response.headers["Content-Language"].startswith("en")


@pytest.mark.django_db
def test_unknown_accept_language_falls_back_to_english(client):
    response = client.get(reverse("buyback:form"), HTTP_ACCEPT_LANGUAGE="xx-YY,zz")

    assert response.status_code == 200
    assert response.headers["Content-Language"].startswith("en")


@pytest.mark.django_db
def test_accept_language_selects_a_configured_locale(client):
    with override_settings(LANGUAGES=TWO_LANGUAGES):
        response = client.get(reverse("buyback:form"), HTTP_ACCEPT_LANGUAGE="eo")

    assert response.headers["Content-Language"].startswith("eo")


@pytest.mark.django_db
def test_cookie_beats_accept_language(client):
    client.cookies["django_language"] = "en"

    with override_settings(LANGUAGES=TWO_LANGUAGES):
        response = client.get(reverse("buyback:form"), HTTP_ACCEPT_LANGUAGE="eo")

    assert response.headers["Content-Language"].startswith("en")


@pytest.mark.django_db
def test_switcher_renders_when_more_than_one_language_is_configured(client):
    """Regression: the switcher was silently absent for the whole feature.

    LANGUAGES was empty in template context because the i18n context processor
    was missing, so `{% if LANGUAGES|length > 1 %}` never fired. Nothing caught
    it because no test rendered base.html with a second locale configured.
    """
    with override_settings(LANGUAGES=TWO_LANGUAGES):
        body = client.get(reverse("buyback:form")).content.decode()

    assert 'name="language"' in body
    assert body.count("<option") == 2


@pytest.mark.django_db
def test_switcher_is_hidden_when_only_one_language_ships(client):
    """Production ships English alone; an empty dropdown would be noise."""
    body = client.get(reverse("buyback:form")).content.decode()

    assert "<select" not in body


@pytest.mark.django_db
def test_html_lang_attribute_follows_the_active_locale(client):
    client.cookies["django_language"] = "eo"

    with override_settings(LANGUAGES=TWO_LANGUAGES):
        body = client.get(reverse("buyback:form")).content.decode()

    assert 'lang="eo"' in body


@pytest.mark.django_db
def test_admin_renders_english_even_with_a_non_english_cookie(client, django_user_model):
    django_user_model.objects.create_superuser("admin", "a@example.com", "pw12345678")
    client.login(username="admin", password="pw12345678")
    client.cookies["django_language"] = "eo"

    with override_settings(LANGUAGES=TWO_LANGUAGES):
        response = client.get("/admin/")

    assert response.status_code == 200
    # The admin's own chrome must stay English regardless of the visitor's choice.
    assert b"Site administration" in response.content or b"Dashboard" in response.content


@pytest.mark.django_db
def test_admin_english_middleware_does_not_leak_into_public_pages(client):
    """The middleware keys on the /admin/ prefix; public pages must be unaffected."""
    client.cookies["django_language"] = "eo"

    with override_settings(LANGUAGES=TWO_LANGUAGES):
        client.get("/admin/")
        response = client.get(reverse("buyback:form"))

    assert response.headers["Content-Language"].startswith("eo")


@pytest.mark.django_db
def test_set_language_view_is_reachable(client):
    response = client.post(
        "/i18n/setlang/", {"language": "en", "next": reverse("buyback:form")}
    )

    assert response.status_code in (302, 200)


def test_production_ships_english_only(settings):
    """Guard: the eo pseudo-locale is a test fixture and must never ship."""
    assert [code for code, _name in settings.LANGUAGES] == ["en"]


def test_translation_actually_activates():
    """Proves the compiled .mo is present and loadable, not just configured."""
    with translation.override("eo"):
        assert translation.gettext("Blacklisted") == "Malpermesita"
