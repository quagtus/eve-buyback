# EVE Client UI Rework — Design

## 1. Purpose

Replace the Nord palette on the public site with EVE Online's in-game client visual language: near-black panels, thin steel borders, chamfered corners, and amber highlights.

The site is a tool players use while docked. It should look like it belongs next to the client window, not like a generic dark web app.

## 2. Decisions

| Question | Decision |
|---|---|
| Light theme | Kept, as an invented "station interior" variant — pale steel panels, same structure. EVE itself has no light mode. |
| Which EVE look | The in-game client UI, not eveonline.com's marketing style. |
| Scope | Everything, including a tint of the django-unfold admin. |
| Window framing | EVE-styled panels laid out as a normal page — not fake window chrome on every section. |

## 3. Approach

**Swap the token values; keep the semantic architecture.**

`--surface`, `--text`, `--accent`, `--danger` and friends stay exactly as they are; only their hex values change. Templates referencing `bg-surface` / `text-accent` need almost no edits.

This is the case semantic tokens were built for — the earlier decision to keep raw palette names out of markup means a whole-theme swap redefines one block instead of touching five templates. It also preserves the WCAG verification workflow, which has already caught two real contrast bugs.

Rejected: EVE-named tokens (`--eve-amber`) would force edits across every template and discard the indirection that makes the *next* swap cheap. Rejected: keeping Nord as a selectable third theme — triple palette maintenance for a single-operator tool.

## 4. Palette

Every value measured, not asserted. All pairs clear WCAG AA (≥ 4.5) against both their base and raised surface.

| Token | Dark (EVE client) | ratio | Light ("station interior") | ratio |
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

**The amber is the only token that changes character between themes.** EVE's signature `#fca311` scores **1.65** on the light surface — unreadable — so light mode darkens it to `#8a5000`. On dark it is used untouched.

EVE's palette needs no other compromises: its near-black backgrounds give far more contrast headroom than Nord's `#2E3440`, which failed twice.

## 5. Component Language

**Chamfered corners** — a diagonal cut, EVE's signature, not a rounded radius. Provided as two utilities, `.eve-chamfer` (panels) and `.eve-chamfer-sm` (controls), rather than repeating `clip-path` polygons in markup.

Two gotchas solved once in the utilities rather than rediscovered per template:

- **`clip-path` clips the border.** A bordered element loses its border along the cut edge. Solved with the wrapper pattern: an outer element painted the border colour and clipped slightly larger, wrapping an inner element painted the fill colour.
- **`clip-path` clips the focus outline.** A keyboard user would see the focus ring cut off or vanish. Focus is therefore an inner amber ring plus a background shift, never an `outline`.

**Panels** — `--surface-raised` fill, 1px `--border` hairline, chamfered bottom-right, with an optional header strip in a darker tone carrying an uppercase, wide-tracked label. The header strip is what makes a section read as an EVE window without fake controls.

**Typography** — a clean sans for prose; the client's condensed face is not web-available and readability beats mimicry for a paragraph of instructions. `tabular-nums` wherever numbers align. Uppercase with wide tracking for labels and table headers. Monospace for codes and ISK figures so digits line up. The grafted dialog's mono-everything is dropped for body text.

**Density** — tighter than the Nord layout. EVE panels are information-dense; compact row padding also fits more line items without scrolling.

**Amber discipline** — `--accent` marks values the seller acts on (code, recipient, ISK total) and interactive controls. It is not general decoration; overused, it stops signalling anything.

## 6. Scope

| File | Change |
|---|---|
| `assets/css/input.css` | Token values swapped; chamfer utilities added |
| `templates/base.html` | Header becomes an EVE command bar; toggle + switcher restyled |
| `buyback/templates/buyback/form.html` | Paste area as a panel with header strip |
| `buyback/templates/buyback/quote.html` | Quote panel + dense table |
| `buyback/templates/buyback/_error.html` | Danger panel |
| `buyback/templates/buyback/_copy_button.html` | Amber-on-hover treatment |
| `pricing/templates/pricing/rule_summary.html` | Inline styles → EVE colours |
| `config/settings.py` | `UNFOLD["COLORS"]` → amber scale anchored at `#8a5000` |

### Deliberate exclusions

**The contract dialog keeps its current styling.** It is a literal replica of a window the seller is about to open, so it should look like the client, not like the site.

**Unfold stays a tinted Tailwind admin.** It exposes only `COLORS.primary` (11 shades) and `COLORS.font`, so it will read as EVE-*coloured*, not EVE-*shaped*. Chamfered admin panels would mean overriding a third-party theme's internals and redoing that work on every upgrade — ongoing maintenance for a back office only the operator sees.

**The admin amber must anchor darker than the site's.** Unfold paints white text on `primary-600`; EVE's raw `#fca311` gives white-on-fill **2.02**, badly failing. Shade 600 is `#8a5000` (6.51).

`pricing/templates/pricing/rule_summary.html` keeps inline styles rather than Tailwind classes: it extends `admin/base_site.html`, which does not load `app.css`, so utility classes would not resolve.

## 7. Testing

Most of the existing suite survives — templates change but semantics do not, and tests assert on content and behaviour rather than class names. The exceptions are the few assertions matching markup (e.g. `bg-danger-surface` in the flagged-row test), which are updated.

New coverage, following the pattern that has already caught four real bugs:

- **Contrast verified in code, not prose.** A test computes WCAG ratios for every token pair in both themes and fails below 4.5, so a future palette tweak cannot silently ship an unreadable amber.
- The no-JS dark default and `prefers-color-scheme` fallback keep their guards, re-pointed at the new values.
- A test asserts the admin's `primary-600` keeps white text legible, locking down the 2.02 failure.
- Template hygiene, static-asset, clipboard, and frozen-quote guards are untouched and must stay green.

## 8. Out of Scope

No layout restructuring beyond density. No new pages. No changes to pricing logic, i18n, the frozen-quote behaviour, or the deployment story.
