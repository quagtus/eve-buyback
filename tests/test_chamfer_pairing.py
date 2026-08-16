"""Every chamfered fill must sit inside a matching frame.

`clip-path` clips an element's border, so a chamfered panel cannot use a CSS
border. The pattern is two nested elements whose clip paths differ by 1px:
the outer `.eve-frame` painted the border colour, the inner `.eve-fill` painted
the fill. That 1px differential IS the visible hairline.

A lone `.eve-fill` therefore renders with no border at all — it looks almost
right, which is what makes it easy to ship.

This replaces a `_panel.html` partial that tried to codify the same rule by
convention. It had zero callers: every template hand-rolled the markup instead,
because Django's `{% include %}` cannot carry block content like forms or
`{% csrf_token %}`. Enforcing the rule beats documenting it.
"""

import glob
import re

import pytest

TEMPLATES = [
    path
    for pattern in ("templates/**/*.html", "*/templates/**/*.html")
    for path in glob.glob(pattern, recursive=True)
]


def test_there_are_templates_to_check():
    """Guard the guard: a bad glob would make the check below vacuous."""
    assert len(TEMPLATES) >= 4


def _strip_comments(source):
    """Prose in comments must not count as markup."""
    source = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", source, flags=re.S)
    return re.sub(r"\{#.*?#\}", "", source, flags=re.S)


@pytest.mark.parametrize("path", TEMPLATES)
def test_every_fill_has_a_frame(path):
    source = _strip_comments(open(path, encoding="utf-8").read())

    fills = len(re.findall(r"\beve-fill(?:-sm)?\b", source))
    frames = len(re.findall(r"\beve-frame(?:-sm)?\b", source))

    if not fills and not frames:
        pytest.skip("template uses no chamfer utilities")

    assert frames >= fills, (
        f"{path}: {fills} eve-fill vs {frames} eve-frame. A fill without a "
        f"frame has no hairline — clip-path eats a plain CSS border."
    )


@pytest.mark.parametrize("path", TEMPLATES)
def test_chamfered_elements_do_not_use_a_css_border(path):
    """A `border-*` on a clipped element is silently eaten along the diagonal."""
    source = _strip_comments(open(path, encoding="utf-8").read())

    offenders = [
        match.group(0)
        for match in re.finditer(r'class="[^"]*"', source)
        if re.search(r"\beve-(?:frame|fill)(?:-sm)?\b", match.group(0))
        and re.search(r"\bborder-(?:[trbl]\b|\d)", match.group(0))
    ]

    assert not offenders, (
        f"{path}: chamfered element carries a CSS border, which clip-path "
        f"clips along the cut: {offenders}"
    )
