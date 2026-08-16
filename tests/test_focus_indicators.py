"""Every suppressed outline must be replaced by a visible focus indicator.

`clip-path` clips an element's focus outline, so chamfered controls use
`focus:outline-none` and express focus by recolouring their frame instead.
That trade is only safe if the replacement actually exists.

Regression this guards: the primary "Get quote" button had frame and fill both
painted `bg-accent`, so `focus-within:bg-accent` was a no-op — `outline-none`
removed the sole focus indicator and keyboard users got nothing on a public
page's main call to action.
"""

import glob
import re

import pytest

TEMPLATES = [
    path
    for pattern in ("templates/**/*.html", "*/templates/**/*.html")
    for path in glob.glob(pattern, recursive=True)
]

SUPPRESSION = "focus:outline-none"
# A frame recolour, or any focus-visible styling, counts as a replacement.
INDICATOR = re.compile(r"focus-within:bg-[a-z-]+|focus-visible:[a-z-]+")


def test_there_are_templates_to_check():
    """Guard the guard: a bad glob would make the check below vacuous."""
    assert len(TEMPLATES) >= 4


@pytest.mark.parametrize("path", [p for p in TEMPLATES])
def test_suppressed_outlines_have_a_replacement_indicator(path):
    source = open(path, encoding="utf-8").read()
    suppressions = source.count(SUPPRESSION)

    if not suppressions:
        pytest.skip("no outline suppression in this template")

    indicators = len(INDICATOR.findall(source))

    assert indicators >= suppressions, (
        f"{path}: {suppressions} × '{SUPPRESSION}' but only {indicators} focus "
        f"indicator(s). A suppressed outline with no replacement leaves keyboard "
        f"users with no visible focus."
    )
