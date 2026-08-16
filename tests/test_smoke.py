def test_settings_import():
    from django.conf import settings

    assert "pricing" in settings.INSTALLED_APPS
    assert "buyback" in settings.INSTALLED_APPS
    assert "catalog" in settings.INSTALLED_APPS
    assert "siteconfig" in settings.INSTALLED_APPS
