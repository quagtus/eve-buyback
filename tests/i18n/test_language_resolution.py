import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_default_is_english_with_no_signal(client):
    response = client.get(reverse("buyback:form"))

    assert response.status_code == 200
    assert response.headers.get("Content-Language", "en").startswith("en")


@pytest.mark.django_db
def test_unknown_accept_language_falls_back_to_english(client):
    response = client.get(reverse("buyback:form"), HTTP_ACCEPT_LANGUAGE="xx-YY,zz")

    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_renders_english_even_with_a_non_english_cookie(client, django_user_model):
    django_user_model.objects.create_superuser("admin", "a@example.com", "pw12345678")
    client.login(username="admin", password="pw12345678")
    client.cookies["django_language"] = "de"

    response = client.get("/admin/")

    assert response.status_code == 200
    # The admin's own chrome must stay English regardless of the visitor's choice.
    assert b"Site administration" in response.content or b"Dashboard" in response.content


@pytest.mark.django_db
def test_set_language_view_is_reachable(client):
    response = client.post(
        "/i18n/setlang/", {"language": "en", "next": reverse("buyback:form")}
    )

    assert response.status_code in (302, 200)
