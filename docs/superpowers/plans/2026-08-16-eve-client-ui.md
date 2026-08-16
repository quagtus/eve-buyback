# EVE Client UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Nord palette on the public site with EVE Online's in-game client visual language — near-black panels, steel hairlines, chamfered corners, amber highlights — keeping an invented "station interior" light theme.

**Architecture:** The existing semantic token architecture is preserved; only token *values* change. Chamfers are added as Tailwind v4 `@utility` definitions using a frame/fill wrapper so the hairline survives `clip-path`. Templates keep referencing semantic classes, so markup churn is minimal.

**Tech Stack:** Tailwind CSS v4.3.3 standalone CLI, Django 5.1 templates, django-unfold 0.43.0.

**Source spec:** `docs/superpowers/specs/2026-08-16-eve-client-ui-design.md`

---

## Verified External Facts

Confirmed empirically while writing this plan. Do not re-derive.

**Tailwind v4 custom utilities**
- The `@utility <name> { ... }` directive is the v4 mechanism. Verified generating `.eve-chamfer { clip-path: ... }` into `@layer utilities`.
- Custom utilities are still purged when unused — verified.
- `source(none)` plus explicit `@source` is already in `assets/css/input.css` and must stay; without it Tailwind scans `docs/*.md` and compiles classes mentioned only in documentation.

**The chamfer border problem, and its solution**
- `clip-path` clips *everything the element paints*, including its `border` and its focus `outline`. A bordered, clipped element loses the border along the cut edge, and a focused one loses the ring entirely.
- Verified solution — two nested elements with clip paths differing by 1px:
  - outer (`.eve-frame`) painted the border colour, clipped at **13px**
  - inner (`.eve-fill`) painted the fill colour, clipped at **12px**, with `p-px` on the outer
  - the 1px differential is the visible hairline, and it follows the chamfered cut
- Verified focus solution: `focus-within:bg-[#fca311]` on the **frame** compiles and works. Focus turns the hairline amber. Nothing relies on `outline`, so nothing gets clipped.

**Measured WCAG ratios** — every pair below clears AA (≥ 4.5) against both its base and raised surface:

| Token | Dark | ratio | Light | ratio |
|---|---|---|---|---|
| `--surface` | `#020508` | — | `#e4e9ec` | — |
| `--surface-raised` | `#0b131a` | — | `#f4f7f8` | — |
| `--border` | `#2a3c4d` | — | `#c2ccd2` | — |
| `--text` | `#cfd8dc` | 12.93 | `#10181f` | 14.64 |
| `--text-muted` | `#8fa3ad` | 7.14 | `#4a5a66` | 5.83 |
| `--accent` | `#fca311` | 9.25 | `#8a5000` | 5.32 |
| `--accent-contrast` | `#020508` | 10.11 | `#ffffff` | 5.60 |
| `--link` | `#64b5f6` | 8.45 | `#1c5f96` | 5.49 |
| `--danger` | `#e57373` | 6.27 | `#a3231f` | 6.09 |
| `--danger-surface` | `#2a1416` | — | `#f7e2e1` | — |

**EVE's amber `#fca311` scores 1.65 on the light surface — unreadable.** It is used untouched on dark and darkened to `#8a5000` on light. This is the only token that changes character between themes.

**Unfold amber scale**, anchored so white-on-`primary-600` stays legible (raw `#fca311` gives **2.02** and fails; `#8a5000` gives **6.51**):

```
50:255 249 240   100:255 240 219  200:255 223 178  300:255 199 122
400:255 169 51   500:224 130 0    600:138 80 0     700:112 65 0
800:92 53 0      900:71 41 0      950:46 27 0
```

**Grep warning for whoever verifies this work:** compiled CSS is minified in the image build but *unminified* under the dev `--watch` sidecar. Any check that greps compiled CSS must normalise whitespace, or it will pass in one build mode and fail in the other. This has already produced two false results during this project.

---

## File Structure

```
assets/css/input.css                          # token values + chamfer utilities
templates/base.html                           # EVE command bar
buyback/templates/buyback/form.html           # paste panel
buyback/templates/buyback/quote.html          # quote panel + dense table
buyback/templates/buyback/_error.html         # danger panel
buyback/templates/buyback/_copy_button.html   # amber hover
buyback/templates/buyback/_panel.html         # NEW: reusable frame/fill panel
pricing/templates/pricing/rule_summary.html   # inline styles -> EVE colours
config/settings.py                            # UNFOLD COLORS
tests/test_contrast.py                        # NEW: WCAG verified in code
```

**Unchanged by design:** the contract dialog block inside `quote.html`. It replicates a window the seller is about to open, so it should keep looking like the client rather than the site.

---

## Task 1: EVE tokens and chamfer utilities

**Files:**
- Modify: `assets/css/input.css`
- Test: `tests/test_contrast.py` (new)

- [ ] **Step 1: Write the failing contrast test**

This encodes the palette as data and verifies it, so a future tweak cannot ship an unreadable colour.

```python
# tests/test_contrast.py
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


@pytest.mark.parametrize("theme_name,theme", [("dark", DARK), ("light", LIGHT)])
def test_every_token_value_reaches_the_compiled_css(theme_name, theme):
    """The table above is only meaningful if these values are what ship."""
    css = re.sub(r"\s+", "", _compiled_css())

    for token, value in theme.items():
        assert value.lower() in css, (
            f"{theme_name}: --{token} value {value} is not in the compiled CSS. "
            f"Did input.css and this test drift apart?"
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec web pytest tests/test_contrast.py -q`
Expected: the pure-maths tests PASS, and `test_every_token_value_reaches_the_compiled_css` FAILS — the compiled CSS still holds the Nord values.

- [ ] **Step 3: Replace the token blocks in `assets/css/input.css`**

Replace the four token blocks (`:root`, the `@media (prefers-color-scheme: light)` block, `:root.light`, `:root.dark`) with these. Dark stays on bare `:root` so no-JS visitors get dark, and the light values appear in all three light positions.

```css
:root {
  --surface: #020508;
  --surface-raised: #0b131a;
  --border: #2a3c4d;
  --text: #cfd8dc;
  --text-muted: #8fa3ad;
  --accent: #fca311;
  --accent-contrast: #020508;
  --link: #64b5f6;
  --danger: #e57373;
  --danger-surface: #2a1416;
}

@media (prefers-color-scheme: light) {
  :root:not(.dark) {
    --surface: #e4e9ec;
    --surface-raised: #f4f7f8;
    --border: #c2ccd2;
    --text: #10181f;
    --text-muted: #4a5a66;
    --accent: #8a5000;
    --accent-contrast: #ffffff;
    --link: #1c5f96;
    --danger: #a3231f;
    --danger-surface: #f7e2e1;
  }
}

:root.light {
  --surface: #e4e9ec;
  --surface-raised: #f4f7f8;
  --border: #c2ccd2;
  --text: #10181f;
  --text-muted: #4a5a66;
  --accent: #8a5000;
  --accent-contrast: #ffffff;
  --link: #1c5f96;
  --danger: #a3231f;
  --danger-surface: #f7e2e1;
}

:root.dark {
  --surface: #020508;
  --surface-raised: #0b131a;
  --border: #2a3c4d;
  --text: #cfd8dc;
  --text-muted: #8fa3ad;
  --accent: #fca311;
  --accent-contrast: #020508;
  --link: #64b5f6;
  --danger: #e57373;
  --danger-surface: #2a1416;
}
```

- [ ] **Step 4: Add `--color-link` to the `@theme` block**

The existing `@theme` block maps tokens to utility-generating colours. `--link` is new, so add one line alongside the others:

```css
  --color-link: var(--link);
```

- [ ] **Step 5: Add the chamfer utilities to `assets/css/input.css`**

Append after the `@theme` block. Replace the existing `.eve-button-chamfer` / `.eve-button-chamfer-border` rules with these — they are the same idea, generalised and given the 1px differential that preserves the hairline.

```css
/* Chamfered corners, EVE's signature diagonal cut.

   clip-path clips everything the element paints — including its border and
   its focus outline. So a chamfered panel cannot use `border`, and a
   chamfered control cannot use `outline` for focus.

   The fix is two nested elements whose clip paths differ by 1px:
     .eve-frame  outer, painted the border colour, clipped 1px larger
     .eve-fill   inner, painted the fill colour, clipped 1px smaller
   The differential is the visible hairline, and it follows the cut.

   Focus is expressed by recolouring the frame (see focus-within in the
   templates), never by an outline, which would be clipped away. */
@utility eve-frame {
  clip-path: polygon(0 0, 100% 0, 100% calc(100% - 13px), calc(100% - 13px) 100%, 0 100%);
}
@utility eve-fill {
  clip-path: polygon(0 0, 100% 0, 100% calc(100% - 12px), calc(100% - 12px) 100%, 0 100%);
}
@utility eve-frame-sm {
  clip-path: polygon(0 0, 100% 0, 100% calc(100% - 7px), calc(100% - 7px) 100%, 0 100%);
}
@utility eve-fill-sm {
  clip-path: polygon(0 0, 100% 0, 100% calc(100% - 6px), calc(100% - 6px) 100%, 0 100%);
}

/* Retained: the contract dialog replicates the in-game window and keeps its
   own button shape. Do not fold these into the utilities above. */
.eve-button-chamfer {
  clip-path: polygon(0 0, 100% 0, 100% 65%, 85% 100%, 0 100%);
}
.eve-button-chamfer-border {
  clip-path: polygon(0 0, 100% 0, 100% 68%, 87% 100%, 0 100%);
}
```

- [ ] **Step 6: Rebuild the CSS and run the test**

Run:
```bash
docker compose exec web tailwindcss -i assets/css/input.css -o static/css/app.css --minify
docker compose exec web pytest tests/test_contrast.py -q
```
Expected: all tests PASS.

If `test_every_token_value_reaches_the_compiled_css` still fails, a token in `input.css` does not match the table — fix `input.css`, not the test.

- [ ] **Step 7: Verify the utilities actually compile**

Custom utilities are purged when unused, so add a temporary probe:

```bash
printf '<div class="eve-frame eve-fill eve-frame-sm eve-fill-sm"></div>\n' >> templates/base.html
docker compose exec web sh -c \
  'tailwindcss -i assets/css/input.css -o /tmp/probe.css >/dev/null 2>&1;
   for c in eve-frame eve-fill eve-frame-sm eve-fill-sm; do
     grep -q "\.$c" /tmp/probe.css && echo "FOUND $c" || echo "MISSING $c"; done'
git checkout templates/base.html
```
Expected: all four `FOUND`.

- [ ] **Step 8: Commit**

```bash
git add assets/css/input.css tests/test_contrast.py
git commit -m "Swap Nord tokens for the measured EVE palette and add chamfer utilities"
```

---

## Task 2: Reusable panel partial

Every restyled section is a frame/fill pair. Building it once keeps the 1px differential and the focus behaviour in one place instead of copied through five templates.

**Files:**
- Create: `buyback/templates/buyback/_panel.html`
- Test: `tests/buyback/test_panel_partial.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/buyback/test_panel_partial.py
from django.template import Context, Template


def render(template_string, **context):
    return Template(template_string).render(Context(context))


def test_panel_renders_frame_and_fill_as_nested_elements():
    """The hairline only exists if BOTH clip layers are present."""
    html = render(
        '{% include "buyback/_panel.html" with title="Assets" body="x" %}'
    )

    assert "eve-frame" in html
    assert "eve-fill" in html
    assert html.index("eve-frame") < html.index("eve-fill"), "frame must wrap fill"


def test_panel_shows_an_uppercase_header_when_titled():
    html = render('{% include "buyback/_panel.html" with title="Assets" %}')

    assert "Assets" in html
    assert "uppercase" in html


def test_panel_omits_the_header_strip_when_untitled():
    html = render('{% include "buyback/_panel.html" %}')

    assert "eve-frame" in html
    assert "uppercase" not in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_panel_partial.py -q`
Expected: FAIL — `TemplateDoesNotExist: buyback/_panel.html`.

- [ ] **Step 3: Create `buyback/templates/buyback/_panel.html`**

```html
{% comment %}
EVE-styled panel: a frame/fill pair.

The outer .eve-frame is painted the border colour and clipped 1px larger than
the inner .eve-fill, so the 1px differential shows as a hairline that follows
the chamfered cut. A plain CSS border would be clipped away.

Usage:
  {% include "buyback/_panel.html" with title=_("Assets") body=some_html %}
Or wrap content by overriding the panel_body block in a caller that extends
this file. For simple cases pass `body`.
{% endcomment %}
<div class="eve-frame bg-border-token p-px">
  <div class="eve-fill bg-surface-raised">
    {% if title %}
      <div class="border-b border-border-token/60 px-4 py-2">
        <span class="text-xs uppercase tracking-[0.15em] text-text-muted">{{ title }}</span>
      </div>
    {% endif %}
    <div class="p-4">{{ body }}</div>
  </div>
</div>
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker compose exec web pytest tests/buyback/test_panel_partial.py -q`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add buyback/templates/buyback/_panel.html tests/buyback/test_panel_partial.py
git commit -m "Add reusable EVE panel partial with frame/fill hairline"
```

---

## Task 3: Base chrome — EVE command bar

**Files:**
- Modify: `templates/base.html`

- [ ] **Step 1: Replace the `<header>` element**

Keep everything else in the file — the pre-paint theme script, the `{% if SITE_LOGO %}` guard, the footer guard, and the toggle script all stay exactly as they are. Replace only the `<header>...</header>` block:

```html
      <header class="mb-8 border-b border-border-token">
        <div class="flex items-center justify-between gap-4 py-3">
          <div class="flex items-center gap-3 min-w-0">
            {% if SITE_LOGO %}
              <img src="{{ SITE_LOGO.url }}" alt="{{ SITE_NAME }} logo"
                   class="h-10 w-10 shrink-0 object-cover border border-border-token">
            {% endif %}
            <a href="{% url 'buyback:form' %}"
               class="truncate text-sm font-semibold uppercase tracking-[0.2em] text-accent no-underline">
              {{ SITE_NAME }}
            </a>
          </div>

          <div class="flex items-center gap-2">
            {% if LANGUAGES|length > 1 %}
              <form action="{% url 'set_language' %}" method="post"
                    hx-post="{% url 'set_language' %}" hx-target="body" hx-swap="outerHTML">
                {% csrf_token %}
                <input type="hidden" name="next" value="{{ request.path }}">
                <label class="sr-only" for="lang">{% translate "Language" %}</label>
                <div class="eve-frame-sm bg-border-token p-px focus-within:bg-accent">
                  <select id="lang" name="language" onchange="this.form.requestSubmit()"
                          class="eve-fill-sm bg-surface-raised px-2 py-1 text-xs uppercase
                                 tracking-wider text-text focus:outline-none">
                    {% get_current_language as CURRENT %}
                    {% for code, name in LANGUAGES %}
                      <option value="{{ code }}" {% if code == CURRENT %}selected{% endif %}>{{ name }}</option>
                    {% endfor %}
                  </select>
                </div>
              </form>
            {% endif %}

            <div class="eve-frame-sm bg-border-token p-px focus-within:bg-accent">
              <button type="button" id="theme-toggle"
                      aria-label="{% translate 'Toggle colour theme' %}"
                      class="eve-fill-sm bg-surface-raised px-3 py-1 text-xs text-text
                             hover:text-accent focus:outline-none">
                <span class="dark:hidden">☾</span>
                <span class="hidden dark:inline">☀</span>
              </button>
            </div>
          </div>
        </div>
      </header>
```

Note `focus-within:bg-accent` on each frame: focus recolours the hairline amber. `focus:outline-none` on the inner control is deliberate — an outline would be clipped by `clip-path` and show as a broken fragment.

- [ ] **Step 2: Set the page background and base type**

Change the `<body>` tag to:

```html
  <body class="bg-surface text-text antialiased text-[15px]">
```

- [ ] **Step 3: Rebuild and check the page renders**

Run:
```bash
docker compose exec web tailwindcss -i assets/css/input.css -o static/css/app.css --minify
curl -s -o /dev/null -w "form page: %{http_code}\n" http://localhost:8000/
```
Expected: `form page: 200`

- [ ] **Step 4: Run the suite**

Run: `docker compose exec web pytest -q`
Expected: all pass. The i18n switcher tests assert on `name="language"` and `<option`, both still present.

- [ ] **Step 5: Commit**

```bash
git add templates/base.html static
git commit -m "Restyle base chrome as an EVE command bar"
```

---

## Task 4: Form page

**Files:**
- Modify: `buyback/templates/buyback/form.html`

- [ ] **Step 1: Replace the whole `{% block content %}`**

```html
{% block content %}
  <div class="eve-frame bg-border-token p-px">
    <div class="eve-fill bg-surface-raised">
      <div class="border-b border-border-token/60 px-4 py-2">
        <span class="text-xs uppercase tracking-[0.15em] text-text-muted">
          {% translate "Item Appraisal" %}
        </span>
      </div>

      <div class="p-4">
        <p class="mb-3 text-sm text-text-muted">
          {% translate "Paste your items below (copy from your in-game inventory) to get a buyback quote." %}
        </p>

        <div id="result"></div>

        <form hx-post="{% url 'buyback:submit' %}" hx-target="#result" hx-swap="innerHTML"
              class="mt-3">
          {% csrf_token %}
          <div class="eve-frame bg-border-token p-px focus-within:bg-accent">
            <textarea name="raw_text" rows="12"
                      placeholder="{% translate 'Raven	1' %}&#10;{% translate 'Tritanium	1000' %}"
                      class="eve-fill w-full bg-surface p-3 font-mono text-sm text-text
                             placeholder:text-text-muted focus:outline-none"></textarea>
          </div>

          <div class="mt-4 inline-block eve-frame-sm bg-accent p-px">
            <button type="submit"
                    class="eve-fill-sm bg-accent px-6 py-2 text-xs font-semibold uppercase
                           tracking-[0.15em] text-accent-contrast hover:brightness-110
                           focus:outline-none">
              {% translate "Get quote" %}
            </button>
          </div>
        </form>

        {% if CONTRACT_TO %}
          <p class="mt-5 text-xs uppercase tracking-wider text-text-muted">
            {% blocktranslate with corp=CONTRACT_TO %}Accepted contracts go to <span class="text-accent">{{ corp }}</span>.{% endblocktranslate %}
          </p>
        {% endif %}
      </div>
    </div>
  </div>
{% endblock %}
```

- [ ] **Step 2: Rebuild and verify**

Run:
```bash
docker compose exec web tailwindcss -i assets/css/input.css -o static/css/app.css --minify
docker compose exec web pytest tests/buyback/test_views.py -q
```
Expected: all pass — the form tests assert on `<form` and on error-partial text, both unchanged.

- [ ] **Step 3: Commit**

```bash
git add buyback/templates/buyback/form.html static
git commit -m "Restyle the paste form as an EVE panel"
```

---

## Task 5: Quote page

The contract dialog block is **not** touched. Only the surrounding page changes.

**Files:**
- Modify: `buyback/templates/buyback/quote.html`
- Modify: `tests/buyback/test_views.py`

- [ ] **Step 1: Replace the heading, note, table and total**

Replace everything from the opening `<h2>` down to and including the `Total offer` paragraph. Leave the `{% if quote.contract_to %}` block and everything after it untouched.

```html
  <div class="eve-frame bg-border-token p-px">
    <div class="eve-fill bg-surface-raised">
      <div class="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-token/60 px-4 py-2">
        <span class="text-xs uppercase tracking-[0.15em] text-text-muted">
          {% translate "Buyback Quote" %}
        </span>
        <span class="font-mono text-sm text-accent">{{ quote.code }}</span>
      </div>

      <div class="px-4 py-3">
        <p class="text-xs text-text-muted">
          {% blocktranslate with created=quote.created_at %}Generated {{ created }}. This page is permanent and will not change.{% endblocktranslate %}
          <a href="{{ quote.janice_url }}" class="text-link underline">{{ quote.janice_url }}</a>
        </p>
      </div>

      <div class="overflow-x-auto border-t border-border-token/60">
        <table class="w-full border-collapse text-sm">
          <thead>
            <tr class="bg-surface/60">
              <th class="px-3 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted">{% translate "Item" %}</th>
              <th class="px-3 py-1.5 text-right text-[11px] font-semibold uppercase tracking-wider text-text-muted">{% translate "Qty" %}</th>
              <th class="px-3 py-1.5 text-right text-[11px] font-semibold uppercase tracking-wider text-text-muted">{% translate "Unit price" %}</th>
              <th class="px-3 py-1.5 text-right text-[11px] font-semibold uppercase tracking-wider text-text-muted">{% translate "Rate" %}</th>
              <th class="px-3 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted">{% translate "Source" %}</th>
              <th class="px-3 py-1.5 text-right text-[11px] font-semibold uppercase tracking-wider text-text-muted">{% translate "Total" %}</th>
            </tr>
          </thead>
          <tbody>
            {% for item in quote.items.all %}
              <tr class="border-t border-border-token/40 {% if item.is_flagged %}bg-danger-surface{% endif %}">
                <td class="px-3 py-1.5 {% if item.is_flagged %}text-danger{% endif %}">
                  {{ item.type_name }}
                  {% if item.is_flagged %}
                    <div class="text-[11px] uppercase tracking-wider">{{ item|flag_reason_label }}</div>
                  {% endif %}
                </td>
                <td class="px-3 py-1.5 text-right font-mono tabular-nums">{{ item.quantity }}</td>
                <td class="px-3 py-1.5 text-right font-mono tabular-nums">{{ item.unit_price }}</td>
                <td class="px-3 py-1.5 text-right font-mono tabular-nums">{{ item.percent_applied }}%</td>
                <td class="px-3 py-1.5 text-xs text-text-muted">{{ item|price_source_label }}</td>
                <td class="px-3 py-1.5 text-right font-mono tabular-nums">{{ item.line_total }}</td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <div class="flex items-baseline justify-between gap-4 border-t border-border-token px-4 py-3">
        <span class="text-xs uppercase tracking-[0.15em] text-text-muted">
          {% translate "Total offer" %}
        </span>
        <span class="font-mono text-2xl font-bold tabular-nums text-accent">
          {{ quote.total_value }} ISK
        </span>
      </div>
    </div>
  </div>
```

Note the total is no longer inside a `{% blocktranslate %}` sentence — the label and the number are separate elements so the amber can be applied to the figure alone. The string `"Total offer"` is still translated.

- [ ] **Step 2: Restyle the "How to sell" heading**

Replace the `<h3>` and its following `<p>` (immediately inside `{% if quote.contract_to %}`) with:

```html
    <h3 class="mt-10 text-xs uppercase tracking-[0.15em] text-text-muted">
      {% translate "How to sell" %}
    </h3>
    <p class="mt-1 text-sm text-text-muted">
      {% translate "Create an in-game contract matching the values below." %}
    </p>
```

- [ ] **Step 3: Confirm no test assertion needs changing**

`tests/buyback/test_views.py::test_quote_page_shows_items_totals_and_flags` asserts
`"140.00" in body` — the bare number, not a combined `"Total offer: 140.00 ISK"` string.
Splitting the label and figure into separate elements therefore does not break it.

Verify rather than assume:

```bash
docker compose exec web pytest tests/buyback/test_views.py::test_quote_page_shows_items_totals_and_flags -q
```
Expected: PASS with no edit. If it fails, the assertion is stricter than expected — update it
to check `"140.00"` and `"Total offer"` independently rather than as one string.

- [ ] **Step 4: Rebuild and run the suite**

Run:
```bash
docker compose exec web tailwindcss -i assets/css/input.css -o static/css/app.css --minify
docker compose exec web pytest -q
```
Expected: all pass.

- [ ] **Step 5: Confirm the contract dialog is untouched**

Run:
```bash
git diff --stat buyback/templates/buyback/quote.html
grep -c "eve-button-chamfer" buyback/templates/buyback/quote.html
```
Expected: the chamfer count is still `2` — the dialog's own buttons are intact.

- [ ] **Step 6: Commit**

```bash
git add buyback/templates/buyback/quote.html tests/buyback/test_views.py static
git commit -m "Restyle the quote page as a dense EVE panel"
```

---

## Task 6: Error partial and copy button

**Files:**
- Modify: `buyback/templates/buyback/_error.html`
- Modify: `buyback/templates/buyback/_copy_button.html`

- [ ] **Step 1: Replace `_error.html` entirely**

```html
<div class="eve-frame bg-danger p-px">
  <div class="eve-fill bg-danger-surface px-4 py-3 text-sm text-danger">
    {{ message }}
  </div>
</div>
```

- [ ] **Step 2: Update the copy button's colours**

In `_copy_button.html`, replace the `class` attribute on the `<button>` with:

```
        class="copy-btn ml-2 inline-flex shrink-0 items-center p-1 align-middle
               text-text-muted transition-colors hover:text-accent focus:outline-none
               focus-visible:text-accent"
```

and change the copied-state icon's colour class from `text-[#7fd67f]` to `text-accent`.

The button keeps `focus:outline-none` plus a colour change rather than a ring: it sits inside the chamfered dialog, where an outline would be clipped.

- [ ] **Step 3: Rebuild and run the suite**

Run:
```bash
docker compose exec web tailwindcss -i assets/css/input.css -o static/css/app.css --minify
docker compose exec web pytest -q
```
Expected: all pass. The clipboard tests assert on `data-copy` attributes, which are unchanged.

- [ ] **Step 4: Commit**

```bash
git add buyback/templates/buyback/_error.html buyback/templates/buyback/_copy_button.html static
git commit -m "Restyle error partial and copy button for the EVE palette"
```

---

## Task 7: Rule summary page

This template extends `admin/base_site.html`, which does not load `app.css`, so Tailwind utilities would not resolve. It keeps inline styles — only the colour values change.

**Files:**
- Modify: `pricing/templates/pricing/rule_summary.html`

- [ ] **Step 1: Replace the inline colour values**

Change these five values throughout the file:

| Old | New | Role |
|---|---|---|
| `#6b7280` | `#4a5a66` | intro paragraph text |
| `#d8dee9` (borders) | `#c2ccd2` | table + row borders |
| `#eceff4` (thead) | `#e4e9ec` | header row background |

Add a wrapping style on the table container so it reads as an EVE panel:

```html
  <div style="overflow-x:auto;border:1px solid #c2ccd2;margin-top:1rem;
              clip-path:polygon(0 0,100% 0,100% calc(100% - 12px),calc(100% - 12px) 100%,0 100%)">
```

The chamfer is applied directly here rather than via the frame/fill utilities, because those are Tailwind classes and this template cannot use them. A single `clip-path` with a plain border is acceptable at this one call site: the border is lost only along the diagonal, and this is a back-office page, not the public site.

- [ ] **Step 2: Verify the page still renders**

Run: `docker compose exec web pytest tests/pricing/test_summary_view.py -q`
Expected: 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add pricing/templates/pricing/rule_summary.html
git commit -m "Recolour the rule summary page for the EVE palette"
```

---

## Task 8: Tint the Unfold admin

**Files:**
- Modify: `config/settings.py`
- Test: `tests/test_contrast.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_contrast.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec web pytest tests/test_contrast.py -k admin -q`
Expected: `test_admin_primary_keeps_white_text_legible` FAILS — the current scale is Nord blue, whose 600 is `#5d81ac`, giving white-on-fill about 4.03.

- [ ] **Step 3: Replace the `UNFOLD["COLORS"]["primary"]` block in `config/settings.py`**

```python
    "COLORS": {
        # EVE amber, anchored so white-on-primary-600 stays legible (6.51).
        # The site's own accent #fca311 would give 2.02 here — Unfold paints
        # white text on this fill, so the admin scale runs darker than the
        # public site's accent on purpose.
        "primary": {
            "50": "255 249 240",
            "100": "255 240 219",
            "200": "255 223 178",
            "300": "255 199 122",
            "400": "255 169 51",
            "500": "224 130 0",
            "600": "138 80 0",
            "700": "112 65 0",
            "800": "92 53 0",
            "900": "71 41 0",
            "950": "46 27 0",
        },
    },
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web pytest tests/test_contrast.py -q`
Expected: all PASS.

- [ ] **Step 5: Confirm the admin still renders**

Run:
```bash
docker compose exec -T web python manage.py shell -c "
from django.test import Client
from django.test.utils import override_settings
from django.contrib.auth.models import User
User.objects.filter(username='probe').exists() or User.objects.create_superuser('probe','p@e.com','pw12345678')
with override_settings(ALLOWED_HOSTS=['testserver']):
    c = Client(); c.login(username='probe', password='pw12345678')
    for url in ('/admin/', '/admin/pricing/customrule/', '/admin/buyback/quote/'):
        print(url, c.get(url).status_code)
"
```
Expected: `200` for all three.

- [ ] **Step 6: Commit**

```bash
git add config/settings.py tests/test_contrast.py
git commit -m "Tint the Unfold admin with a legible EVE amber scale"
```

---

## Task 9: Full verification

No new code — this proves the assembled result.

- [ ] **Step 1: Rebuild the image from scratch**

Run:
```bash
docker compose build web
docker compose up -d
```
Expected: build succeeds, including the Tailwind step.

- [ ] **Step 2: Confirm the stylesheet is built and collected**

Run:
```bash
docker run --rm --entrypoint sh eve-buyback-web:latest -c \
  'echo "static:      $(wc -c < static/css/app.css)";
   echo "staticfiles: $(wc -c < staticfiles/css/app.css)"'
```
Expected: both non-zero.

- [ ] **Step 3: Run the full suite**

Run: `docker compose exec web pytest -q`
Expected: all pass, zero xfails. Record the count.

- [ ] **Step 4: Verify both themes render and no Nord value survives**

Run:
```bash
docker compose exec web sh -c \
  'css=$(tr -d " \n" < static/css/app.css);
   for old in 2e3440 3b4252 88c0d0 acb6c6 e0a0a6; do
     case "$css" in *"#$old"*) echo "STALE NORD #$old";; *) echo "ok: #$old gone";; esac; done;
   for new in 020508 0b131a fca311 8fa3ad e57373; do
     case "$css" in *"#$new"*) echo "ok: #$new present";; *) echo "MISSING #$new";; esac; done'
```
Expected: every line starts `ok:`.

Note the `tr -d " \n"` — compiled CSS is minified in the image build but unminified under the dev watcher, and an unnormalised grep gives different answers in each mode.

- [ ] **Step 5: Verify the no-JS dark default survived the palette swap**

`tests/test_static_assets.py:58` currently asserts `"--surface:#2e3440"` — the old Nord
dark surface. This **will** fail after the palette swap; it is not a conditional. Update it
first, then run:

```python
    assert "--surface:#020508" in by_selector[":root"], (
        "bare :root must carry the DARK surface so no-JS visitors get dark"
    )
```

Run: `docker compose exec web pytest tests/test_static_assets.py -q`
Expected: PASS. The test is still load-bearing — it fails if the light values are ever moved
onto bare `:root`, which is what would break the no-JS dark default.

- [ ] **Step 6: Eyeball the live pages**

Run:
```bash
for u in / /admin/login/ /static/css/app.css; do
  printf "%-22s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000$u)"
done
```
Expected: `200` for all three. Then open `http://localhost:8000/` and confirm: near-black page, amber site name, chamfered panel corners, and that tabbing to the theme toggle turns its hairline amber rather than showing a clipped outline fragment.

- [ ] **Step 7: Commit any fixes**

```bash
git add -A
git commit -m "Fix issues found during EVE UI verification"
```

---

## Plan Self-Review

**Spec coverage:**

| Spec section | Covered by |
|---|---|
| §3 Swap values, keep architecture | Task 1 Steps 3–4 |
| §4 Measured palette, both themes | Task 1 (encoded as test data) |
| §4 Amber differs only in light | Task 1 `test_light_mode_does_not_use_the_raw_eve_amber` |
| §5 Chamfer utilities | Task 1 Step 5 |
| §5 clip-path clips the border | Task 1 Step 5 (frame/fill differential) |
| §5 clip-path clips focus outline | Tasks 3, 4, 6 (`focus-within` + `focus:outline-none`) |
| §5 Panels with header strip | Task 2 |
| §5 Typography, density | Tasks 3–5 |
| §5 Amber discipline | Task 5 (accent on code and total only) |
| §6 base.html | Task 3 |
| §6 form.html | Task 4 |
| §6 quote.html | Task 5 |
| §6 _error.html, _copy_button.html | Task 6 |
| §6 rule_summary.html | Task 7 |
| §6 UNFOLD COLORS | Task 8 |
| §6 Contract dialog unchanged | Task 5 Step 5 (asserted) |
| §7 Contrast verified in code | Task 1 Step 1 |
| §7 Admin primary-600 legibility | Task 8 Step 1 |
| §7 Existing guards stay green | Task 9 Steps 3, 5 |

No spec requirement is unimplemented.

**Placeholder scan:** none. Every step contains complete code or an exact command. Task 5 Step 3 and Task 9 Step 5 describe conditional edits, but both state the exact old and new values rather than deferring the decision.

**Type consistency:** the utilities `eve-frame` / `eve-fill` / `eve-frame-sm` / `eve-fill-sm` are defined in Task 1 Step 5 and used with identical names in Tasks 2, 3, 4, 6. Token names (`--surface`, `--surface-raised`, `--border`, `--text`, `--text-muted`, `--accent`, `--accent-contrast`, `--link`, `--danger`, `--danger-surface`) are identical across the `input.css` blocks, the `@theme` mapping, and `tests/test_contrast.py`'s `DARK` / `LIGHT` dicts — `test_every_token_value_reaches_the_compiled_css` fails if they drift. The Tailwind class for `--border` is `border-token` (not `border`), matching the existing `--color-border-token` mapping.

**Known follow-ups, out of scope:**
- Unfold remains EVE-*coloured*, not EVE-*shaped*. Chamfering the admin would mean overriding a third-party theme's internals and redoing it on every upgrade.
- `rule_summary.html` uses a bare `clip-path` without the frame/fill pattern, so its border is lost along the diagonal. Accepted: it is a back-office page that cannot load `app.css`.
