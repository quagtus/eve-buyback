# Frontend Overhaul: Tailwind, Nord, and i18n — Design

## 1. Purpose

Replace the hand-written CSS in `templates/base.html` with a Tailwind-built Nord design system, add light/dark theming, and make the public site translatable with an instant language switcher.

Three constraints shape everything below:

- The domain layer (`pricing/domain/`, `buyback/domain/`) must stay Django-free, so it cannot call `gettext`. Translation happens at the presentation layer only.
- Snapshots are frozen forever. Whatever is stored must remain a stable record.
- Only strings that belong to **buyback** get translated. Anything originating from EVE, or authored by the admin as data, is left verbatim.

## 2. The Translation Boundary

Every user-visible string falls into one of four buckets:

| Source | Example | Translate? |
|---|---|---|
| EVE data via Janice | `Raven`, `Tritanium` | Never |
| Admin-authored rule names | `Raven Special`, `Battleships` | Never — it's data, not UI |
| Buyback system labels | `Blacklisted`, `No rule configured` | Yes |
| UI chrome | `Total offer`, `Get quote` | Yes |

The current schema cannot express this boundary. `SnapshotItem.price_source` holds *either* a system label (`'Blacklisted'`) or an admin rule name (`'Raven Special'`), so at render time the two are indistinguishable — a rule literally named "Blacklisted" would be ambiguous. Splitting the column is what makes the boundary enforceable rather than a convention.

## 3. Data Model Changes

### Domain (stays pure Python)

- `pricing/domain/resolution.py` stops flattening its result into `source_label="Blacklisted"`. It returns the existing `PriceSourceKind` enum plus, separately, the matched rule's name (empty for system sources).
- `buyback/domain/quote.py` gains a `FlagReason` enum — `UNRECOGNIZED`, `UNPARSEABLE`, `BLACKLISTED`, `NO_RULE` — replacing its hardcoded English strings.

### Persistence

`SnapshotItem`:

- `price_source` → **split** into:
  - `price_source_kind` — enum key (`BLACKLIST` / `SALE` / `CUSTOM` / `CATEGORY_DEFAULT` / `NONE`)
  - `price_source_label` — the admin's rule name; blank for system sources
- `flag_reason` → `flag_reason_code` — enum key, nullable

### Render

A template filter maps kind/code to a translated string. Rule names print verbatim. Display logic: if `price_source_kind` is `SALE` or `CUSTOM`, show `price_source_label`; otherwise show the translated kind.

Frozen-ness is preserved and arguably strengthened — a key is a more stable record of *why* an item was rejected than an English sentence that might later be reworded.

### Migration

A data migration converts existing rows by mapping known English strings back to keys. Unrecognized legacy values degrade to `NONE`/null rather than failing the migration. A reverse migration is provided. This is the only irreversible-in-spirit step in the project, so it is verified against the real rows before commit.

## 4. i18n Mechanics

**Foundation.** Django `LocaleMiddleware`, `USE_I18N = True`, `LANGUAGES = [("en", "English")]`, `LOCALE_PATHS = [BASE_DIR / "locale"]`. Public strings wrapped in `{% translate %}` / `{% blocktranslate %}` in templates and `gettext_lazy` in Python. `makemessages` produces `.po` files for translators; adding a locale later is a directory plus a translation pass, with no code change.

**Language resolution order** (first match wins):

1. Explicit choice, persisted in the `django_language` cookie
2. Browser `Accept-Language`, if it matches a configured locale
3. English

This is Django's built-in `LocaleMiddleware` behaviour exactly — no custom resolution code.

**Admin stays English.** `LocaleMiddleware` would otherwise translate the Django admin and Unfold automatically. A small middleware, ordered after it, forces `translation.activate("en")` for any path under `/admin/`. This also covers the rule summary page, which lives in the admin shell: it receives the Nord restyle but no translation.

**The switcher.** A header dropdown posting to Django's `set_language` view. With one language configured it renders but has nothing to switch to; it becomes live the moment a second locale is added, with no further work. An HTMX request swaps the page's main content and sets the cookie in one round trip — no white flash, scroll position preserved. Without JavaScript it degrades to a plain form post and still works.

**Shipping scope.** English only. All public strings wrapped, extraction configured, switcher built. No second locale's translations are authored.

## 5. Tailwind Build

The standalone Tailwind CLI **binary** is fetched in the `Dockerfile` — no Node, no npm, no `package.json` in a Python project.

- Source: `assets/css/input.css`
- Output: `static/css/app.css`, consumed by the existing `collectstatic` + WhiteNoise pipeline
- Production: compiled during image build
- Development: a `tailwind` sidecar service in `docker-compose.yml` runs `--watch` against the existing bind-mount, so template edits recompile automatically

The Tailwind version and CLI download URL are **pinned explicitly**, not tracked as `latest`, and verified against upstream during planning rather than written from memory.

## 6. Nord Theming

**Semantic tokens, not raw Nord names in markup.** The Nord palette is declared once as CSS custom properties, then mapped to semantic roles: `--surface`, `--surface-raised`, `--text`, `--text-muted`, `--accent`, `--danger`, `--border`. Templates reference the semantic names only. A theme swap redefines the token values in one block instead of hunting `nord3` through five templates, and "flagged row" is defined once rather than each template choosing its own red.

**Palette mapping:**

- Dark (default): Polar Night surfaces (`#2E3440` → `#4C566A`), Snow Storm text
- Light: Snow Storm surfaces (`#ECEFF4` → `#D8DEE9`), Polar Night text
- Accent: Frost `#5E81AC` / `#88C0D0` for actions and links
- Flagged rows: Aurora `#BF616A`, used muted — a rejected item is information, not an alarm

**Theme resolution**, deliberately mirroring the language rule: use `prefers-color-scheme` when the OS states one, otherwise dark. An explicit toggle overrides and persists in `localStorage`. A small inline script in `<head>` sets the root class **before first paint**, preventing the flash of wrong theme that is the usual failure mode of a JS toggle.

**Contrast over fidelity.** Nord's light variant is genuinely low-contrast — `#D8DEE9` surfaces against `#4C566A` muted text sits near the WCAG AA floor. Light-mode muted text is darkened beyond literal Nord so the quote page stays readable. This is a deliberate, approved deviation.

**Restyle scope:** `base.html` (gains a header with theme toggle and language switcher), `form.html`, `snapshot.html`, `_error.html`, `rule_summary.html`. Unfold's admin chrome gets its accent colours tinted toward Nord via its `COLORS` setting so the admin does not clash with the public site.

## 7. Testing

**Existing suite.** All 101 tests must continue to pass. The `SnapshotItem` field split touches assertions in `test_quote.py`, `test_services.py`, and `test_views.py`; those are updated to assert on keys, which is stricter than matching English prose.

**New coverage:**

- Translation boundary: under an active non-English locale, an item named `Raven` and a rule named `Raven Special` render verbatim while system labels translate
- Language resolution: cookie beats `Accept-Language` beats English; an unrecognized `Accept-Language` falls back rather than erroring
- Admin renders English even with a non-English cookie set
- Data migration: existing rows map to correct keys; an unrecognized legacy string degrades instead of failing
- Theme: no-JS renders dark; the pre-paint script sets the root class before first paint

**Pipeline verification without shipping a translation.** Because only English ships, the i18n pipeline would otherwise be untested — extraction and activation can break silently. Tests use a throwaway pseudo-locale fixture containing a handful of translated strings to assert activation, cookie handling, `Accept-Language` detection, and fallback. That locale is test-only and never ships.

## 8. Risks

- **The data migration** rewrites frozen snapshot rows. It ships with a reverse migration and is verified against the real existing rows before commit.
- **The Tailwind CLI** is a new external build-time dependency. Pinned by version; if the URL moves, image builds fail loudly rather than silently producing stale CSS.

## 9. Out of Scope

No new pages. No changes to pricing logic or the Janice integration. No Redis. No second locale's actual translations. No changes to the rate-limiting or deployment story.
