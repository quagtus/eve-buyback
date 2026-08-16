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
