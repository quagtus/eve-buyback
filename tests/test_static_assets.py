"""Guard that the compiled stylesheet is actually reachable.

This exists because it once was not. Tailwind compiled to static/css/app.css,
but STATICFILES_DIRS was empty, so Django never saw the directory:
{% static 'css/app.css' %} resolved to a URL that 404'd and collectstatic
silently omitted the file. The whole site rendered unstyled in both dev and
production while every test passed, because the rest of the suite asserts on
HTML and never on whether the stylesheet resolves.
"""

import re

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


def test_no_js_visitors_get_the_dark_theme():
    """Dark is the default and must not depend on JavaScript.

    Regression: the dark tokens lived only under `:root.dark`, a class set
    exclusively by the pre-paint script. With JS disabled the light block
    applied unconditionally — the opposite of the stated default.
    """
    raw = open(finders.find("css/app.css"), encoding="utf-8").read().lower()
    # Normalise whitespace: the dev --watch build is unminified while the
    # image build passes --minify, so spacing around ":" and ";" differs.
    css = re.sub(r"\s+", "", raw)

    # Match the token block specifically. A naive search for the first ":root"
    # finds Tailwind's own preflight block, which carries no design tokens.
    token_blocks = re.findall(r"(:root[^{]*)\{([^}]*--surface:[^}]*)\}", css)
    by_selector = {sel.strip(): body for sel, body in token_blocks}

    assert ":root" in by_selector, "no bare :root token block found"
    assert "--surface:#2e3440" in by_selector[":root"], (
        "bare :root must carry the DARK surface so no-JS visitors get dark"
    )
    assert "prefers-color-scheme:light" in css, (
        "no OS-preference fallback: light mode unreachable without JS"
    )
    assert ":root.light" in by_selector, "explicit light override missing"
    assert ":root.dark" in by_selector, "explicit dark override missing"
