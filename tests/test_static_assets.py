"""Guard that the compiled stylesheet is actually reachable.

This exists because it once was not. Tailwind compiled to static/css/app.css,
but STATICFILES_DIRS was empty, so Django never saw the directory:
{% static 'css/app.css' %} resolved to a URL that 404'd and collectstatic
silently omitted the file. The whole site rendered unstyled in both dev and
production while every test passed, because the rest of the suite asserts on
HTML and never on whether the stylesheet resolves.
"""

from django.contrib.staticfiles import finders
from django.templatetags.static import static


def test_compiled_stylesheet_is_findable():
    """collectstatic and the dev server both rely on this resolving."""
    assert finders.find("css/app.css") is not None, (
        "css/app.css is not on any static finder path. "
        "Check STATICFILES_DIRS includes BASE_DIR / 'static'."
    )


def test_static_url_for_stylesheet_is_well_formed():
    assert static("css/app.css").endswith("css/app.css")


def test_stylesheet_contains_compiled_tailwind_output():
    """A stale or empty file would still be 'findable' but useless."""
    path = finders.find("css/app.css")
    content = open(path, encoding="utf-8").read()

    assert "tailwindcss" in content, "app.css does not look like Tailwind output"
    # Semantic tokens must survive compilation — these are what the templates use.
    for token in ("--surface", "--text-muted", "--danger"):
        assert token in content, f"design token {token} missing from compiled CSS"
