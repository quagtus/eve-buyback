"""Catch template mistakes that render as visible text instead of failing loudly."""

import glob
import re

import pytest

TEMPLATES = [
    f for f in glob.glob("**/*.html", recursive=True)
    if "/.git/" not in f and "staticfiles/" not in f
]


def test_there_are_templates_to_check():
    """Guard the guard: a bad glob would make every check below vacuous."""
    assert len(TEMPLATES) >= 4


@pytest.mark.parametrize("path", TEMPLATES)
def test_no_multiline_django_comments(path):
    """`{# #}` is single-line only; a multi-line one renders as page text.

    Regression: two multi-line `{# #}` blocks shipped and their contents were
    visible to end users on the quote page and every page using base.html.
    Multi-line comments must use `{% comment %}...{% endcomment %}`.
    """
    source = open(path, encoding="utf-8").read()

    offenders = [
        m.group(0)[:60]
        for m in re.finditer(r"\{#(.*?)#\}", source, re.S)
        if "\n" in m.group(1)
    ]

    assert not offenders, (
        f"{path}: multi-line {{# #}} comment renders as visible text. "
        f"Use {{% comment %}}...{{% endcomment %}}. Found: {offenders}"
    )


@pytest.mark.parametrize("path", TEMPLATES)
def test_title_block_contains_no_markup_or_script(path):
    """`{% block title %}` renders inside <title>, which is text-only.

    Regression: a mis-scoped edit consumed the title block's {% endblock %} and
    the whole clipboard script ended up inside <title> — browser tabs showed
    1740 characters of JavaScript. Every test still passed, because none of
    them looked at the title.
    """
    source = open(path, encoding="utf-8").read()

    # `endblock` must be the whole tag name: a lazy match on "endblock" alone
    # also matches {% endblocktranslate %}, which stops the capture early and
    # makes this check vacuous for exactly the template it guards.
    match = re.search(
        r"\{%\s*block title\s*%\}(.*?)\{%\s*endblock\s*%\}", source, re.S
    )
    if not match:
        pytest.skip("template defines no title block")

    body = match.group(1)

    assert "<script" not in body, f"{path}: <script> inside the title block"
    assert "<div" not in body, f"{path}: <div> inside the title block"
    assert len(body) < 200, (
        f"{path}: title block is {len(body)} chars — it has probably swallowed "
        f"content that belongs in another block"
    )
