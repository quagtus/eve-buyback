"""WCAG contrast is verified in code, not asserted in prose.

Literal Nord shipped two failures earlier in this project (1.69 for dark muted
text, 3.05 for flagged-row text) and they were only caught by measuring. This
test makes the palette self-checking.
"""

import re

import pytest
from django.contrib.staticfiles import finders

AA_NORMAL = 4.5

DARK = {
    "surface": "#020508",
    "surface-raised": "#0b131a",
    "border": "#2a3c4d",
    "text": "#cfd8dc",
    "text-muted": "#8fa3ad",
    "accent": "#fca311",
    "accent-contrast": "#020508",
    "link": "#64b5f6",
    "danger": "#e57373",
    "danger-surface": "#2a1416",
}

LIGHT = {
    "surface": "#e4e9ec",
    "surface-raised": "#f4f7f8",
    "border": "#c2ccd2",
    "text": "#10181f",
    "text-muted": "#4a5a66",
    "accent": "#8a5000",
    "accent-contrast": "#ffffff",
    "link": "#1c5f96",
    "danger": "#a3231f",
    "danger-surface": "#f7e2e1",
}

# Foreground tokens must clear AA against BOTH surfaces they can sit on.
FOREGROUNDS = ["text", "text-muted", "accent", "link", "danger"]


def _luminance(hex_colour):
    hex_colour = hex_colour.lstrip("#")
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(a, b):
    la, lb = _luminance(a), _luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_ratio_matches_known_values():
    """Guard the guard: a broken formula would make every check below vacuous."""
    assert round(contrast_ratio("#ffffff", "#000000"), 2) == 21.0
    assert round(contrast_ratio("#ffffff", "#ffffff"), 2) == 1.0


@pytest.mark.parametrize("theme_name,theme", [("dark", DARK), ("light", LIGHT)])
@pytest.mark.parametrize("token", FOREGROUNDS)
@pytest.mark.parametrize("surface", ["surface", "surface-raised"])
def test_foreground_tokens_clear_wcag_aa(theme_name, theme, token, surface):
    ratio = contrast_ratio(theme[token], theme[surface])

    assert ratio >= AA_NORMAL, (
        f"{theme_name}: --{token} ({theme[token]}) on --{surface} "
        f"({theme[surface]}) is {ratio:.2f}, below AA {AA_NORMAL}"
    )


@pytest.mark.parametrize("theme_name,theme", [("dark", DARK), ("light", LIGHT)])
def test_accent_contrast_is_legible_on_accent(theme_name, theme):
    """accent-contrast is the text colour painted ON an accent fill."""
    ratio = contrast_ratio(theme["accent-contrast"], theme["accent"])

    assert ratio >= AA_NORMAL, f"{theme_name}: text on accent is {ratio:.2f}"


@pytest.mark.parametrize("theme_name,theme", [("dark", DARK), ("light", LIGHT)])
def test_danger_is_legible_on_its_own_surface(theme_name, theme):
    ratio = contrast_ratio(theme["danger"], theme["danger-surface"])

    assert ratio >= AA_NORMAL, f"{theme_name}: danger on danger-surface is {ratio:.2f}"


def test_light_mode_does_not_use_the_raw_eve_amber():
    """EVE's #fca311 scores 1.65 on the light surface — unreadable.

    It is correct on dark and must never be copied across.
    """
    assert LIGHT["accent"] != "#fca311"
    assert DARK["accent"] == "#fca311"


def _compiled_css():
    return open(finders.find("css/app.css"), encoding="utf-8").read().lower()


def _hex_shorthand(value):
    """The minified build (lightningcss) collapses #rrggbb to #rgb whenever

    each channel repeats a digit — valid CSS, e.g. #ffffff -> #fff. Only
    --accent-contrast's #ffffff qualifies among this file's tokens, but a
    literal substring check would otherwise pass against the unminified dev
    --watch output and fail against the minified image build. Returns None
    when no channel-doubling applies, i.e. no shorthand exists.
    """
    digits = value.lstrip("#")
    if len(digits) == 6 and all(digits[i] == digits[i + 1] for i in (0, 2, 4)):
        return "#" + "".join(digits[i] for i in (0, 2, 4))
    return None


@pytest.mark.parametrize("theme_name,theme", [("dark", DARK), ("light", LIGHT)])
def test_every_token_value_reaches_the_compiled_css(theme_name, theme):
    """The table above is only meaningful if these values are what ship."""
    css = re.sub(r"\s+", "", _compiled_css())

    for token, value in theme.items():
        shorthand = _hex_shorthand(value)
        present = value.lower() in css or (
            shorthand is not None and shorthand.lower() in css
        )
        assert present, (
            f"{theme_name}: --{token} value {value} is not in the compiled CSS. "
            f"Did input.css and this test drift apart?"
        )
