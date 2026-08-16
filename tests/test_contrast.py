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


def _hex_shorthand(value):
    """The minified build (lightningcss) collapses #rrggbb to #rgb whenever
    each channel repeats a digit — valid CSS, e.g. #ffffff -> #fff.

    Only --accent-contrast's #ffffff qualifies among these tokens, but a
    literal comparison would otherwise pass against the unminified dev
    --watch output and fail against the minified image build. Returns None
    when no shorthand exists.
    """
    digits = value.lstrip("#")
    if len(digits) == 6 and all(digits[i] == digits[i + 1] for i in (0, 2, 4)):
        return "#" + "".join(digits[i] for i in (0, 2, 4))
    return None


def _compiled_css():
    return open(finders.find("css/app.css"), encoding="utf-8").read().lower()


def _token_blocks(css):
    """Map each theme selector to its token -> value bindings.

    Presence alone is not enough. Both themes' values live in the same
    stylesheet, so a check that merely asks "does #fca311 appear anywhere"
    passes even when a block binds the wrong colour — verified: corrupting
    :root's accent left :root.dark's copy behind and the check still passed.
    Parsing the bindings per block is what actually catches a bad swap.
    """
    flat = re.sub(r"\s+", "", css)
    blocks = {}
    for selector, body in re.findall(r"(:root(?:\.[a-z]+|:not\(\.[a-z]+\))?)\{([^}]*)\}", flat):
        if "--surface:" not in body:
            continue  # Tailwind's own :root preflight carries no design tokens
        blocks[selector] = dict(re.findall(r"--([a-z-]+):(#[0-9a-f]{3,6})", body))
    return blocks


def _matches(actual, expected):
    """Compare allowing the minifier's #rrggbb -> #rgb shorthand."""
    if actual == expected:
        return True
    shorthand = _hex_shorthand(expected)
    return shorthand is not None and actual == shorthand.lower()


@pytest.mark.parametrize(
    "selector,theme,label",
    [
        (":root", DARK, "bare :root (the no-JS default)"),
        (":root.dark", DARK, "explicit dark"),
        (":root.light", LIGHT, "explicit light"),
        (":root:not(.dark)", LIGHT, "OS-prefers-light fallback"),
    ],
)
def test_each_theme_block_binds_the_expected_token_values(selector, theme, label):
    blocks = _token_blocks(_compiled_css())

    assert selector in blocks, f"{label}: no token block for {selector} in compiled CSS"

    for token, expected in theme.items():
        actual = blocks[selector].get(token)
        assert actual is not None, f"{label}: --{token} missing from {selector}"
        assert _matches(actual, expected.lower()), (
            f"{label}: --{token} is {actual} in {selector}, expected {expected}"
        )


def test_admin_primary_keeps_white_text_legible():
    """Unfold paints white text on primary-600.

    EVE's raw amber #fca311 gives white-on-fill 2.02 and fails badly. The admin
    scale must anchor darker than the site's accent for this reason alone.
    """
    from django.conf import settings

    primary = settings.UNFOLD["COLORS"]["primary"]
    red, green, blue = (int(part) for part in primary["600"].split())
    fill = f"#{red:02x}{green:02x}{blue:02x}"

    ratio = contrast_ratio("#ffffff", fill)

    assert ratio >= AA_NORMAL, (
        f"white on admin primary-600 ({fill}) is {ratio:.2f}; "
        f"anchor the scale darker"
    )


def test_admin_scale_has_every_shade_unfold_requires():
    from django.conf import settings

    primary = settings.UNFOLD["COLORS"]["primary"]
    expected = {"50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"}

    assert set(primary) == expected


def test_admin_scale_uses_unfolds_space_separated_rgb_format():
    """Not hex, not comma-separated — Unfold parses 'R G B'."""
    from django.conf import settings

    for shade, value in settings.UNFOLD["COLORS"]["primary"].items():
        parts = value.split()
        assert len(parts) == 3, f"shade {shade} is {value!r}, expected 'R G B'"
        assert all(part.isdigit() and 0 <= int(part) <= 255 for part in parts)
