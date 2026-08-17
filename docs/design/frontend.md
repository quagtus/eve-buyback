# Frontend

Covers the design system, theming, and internationalisation of the public site.

## Design system

The UI follows EVE Online's in-game client: near-black panels, thin steel
hairlines, chamfered corners, amber highlights. The site is a tool players use
while docked, so it should sit comfortably beside the game client.

### Tokens

Colours are semantic CSS custom properties (`--surface`, `--text`, `--accent`,
`--danger`, …) defined once in `assets/css/input.css` and mapped into Tailwind
through its `@theme` block. Templates reference the semantic names only.

The indirection is the point: a whole-theme change redefines one block rather
than touching every template. The palette has been swapped once already
(Nord → EVE) and the templates needed almost no edits.

### Contrast

Every foreground token clears WCAG AA (≥ 4.5) against both the base and raised
surface, in both themes. This is enforced by `tests/test_contrast.py`, which
holds the palette as data, computes the ratios, and additionally parses the
compiled CSS to confirm each theme block binds the values it should.

Two deviations from literal EVE colours, both forced by measurement:

| Token | Value | Why |
|---|---|---|
| light `--accent` | `#8a5000` | EVE's amber `#fca311` scores **1.65** on the light surface — unreadable. Used untouched on dark (9.25). |
| admin `primary-600` | `#8a5000` | django-unfold paints white text on this fill; the raw amber gives **2.02**. |

### Themes

Dark is the default and works without JavaScript: the dark values sit on bare
`:root`, with light reached through `@media (prefers-color-scheme: light)
:root:not(.dark)`. An explicit toggle sets `.dark` or `.light` and persists the
choice; a small inline script in `<head>` applies it before first paint to avoid
a flash of the wrong theme.

The light theme is an invention — EVE has no light mode — kept for daylight
readability.

### Chamfers

The diagonal corner cut is EVE's signature. It is implemented with `clip-path`,
which carries two traps worth knowing before editing any panel:

- **`clip-path` clips the element's border.** A chamfered box cannot use a CSS
  border; it would vanish along the diagonal. Panels are therefore a *frame/fill
  pair*: an outer element painted the border colour clipped 1px larger, wrapping
  an inner element painted the fill. That 1px differential is the visible
  hairline, and it follows the cut. `tests/test_chamfer_pairing.py` enforces
  this — a lone fill fails.
- **`clip-path` also clips the focus outline.** Chamfered controls therefore use
  `focus:outline-none` and express focus by recolouring the frame instead.
  `tests/test_focus_indicators.py` asserts every suppressed outline has a
  replacement, so the trade never silently drops keyboard accessibility.

### Build

Tailwind is compiled by the **standalone CLI binary** — no Node, no
`package.json` in a Python project. Version is pinned in the `Dockerfile`.

Tailwind v4 uses CSS-first configuration; there is no `tailwind.config.js`.
Custom utilities are declared with `@utility`.

`@import "tailwindcss" source(none)` is deliberate. Without it Tailwind scans the
entire project — including markdown in `docs/` — and compiles every class
mentioned in documentation into the shipped stylesheet. Only the three template
directories declared with `@source` are scanned.

One gotcha when inspecting the compiled output: the image build minifies it, the
dev `--watch` sidecar does not. Any check that greps `static/css/app.css` must
normalise whitespace first, or it will answer differently in the two modes.

## Internationalisation

The public site is translatable. Only English ships; the machinery is in place
so adding a locale is a directory and a translation pass, with no code change.

### What gets translated

The boundary is the rule that matters:

| Source | Example | Translated? |
|---|---|---|
| EVE data via Janice | `Raven`, `Tritanium` | Never |
| Admin-authored rule names | `Raven Special` | Never — it is data, not UI |
| Buyback's own system labels | `Blacklisted`, `No rule configured` | Yes |
| UI chrome | `Total offer`, `Get quote` | Yes |

The schema enforces this rather than leaving it to convention. `QuoteItem`
stores `price_source_kind` (a machine key, translated at render) separately from
`price_source_label` (the operator's rule name, printed verbatim). A single
column could not express the distinction — a rule literally named "Blacklisted"
would be indistinguishable from the system source.

The domain layer stays free of Django imports, so it cannot call `gettext`; it
emits enum keys and the presentation layer resolves them through
`buyback/templatetags/buyback_labels.py`.

### Language resolution

Standard `LocaleMiddleware` behaviour, first match wins:

1. Explicit choice, persisted in the `django_language` cookie
2. Browser `Accept-Language`, if it matches a configured locale
3. English

The admin is deliberately **not** translated — `AdminEnglishMiddleware` forces
English for `/admin/` paths, including the rule summary page.

### Numbers

`buyback/templatetags/eve_formats.py` formats ISK and quantities EVE-style:
space-separated thousands, dot decimal, identical in every locale. This
deliberately bypasses Django's locale formatting, because a player copying a
figure into the game client needs the form the client accepts — a comma decimal
separator would be rejected.

Values are handled as `Decimal`, never `float`: converting through float loses a
cent around 1e14.
