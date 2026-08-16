# Frontend Nord + i18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-written CSS with a Tailwind-built Nord design system with light/dark theming, and make the public site translatable with an instant HTMX language switcher.

**Architecture:** The domain layer stays Django-free, so it emits enum keys instead of English display text; translation happens only at the presentation layer via a template filter. Tailwind compiles via a standalone binary (no Node) into the existing WhiteNoise static pipeline. Nord is expressed as semantic CSS custom properties so a theme swap redefines one block.

**Tech Stack:** Django 5.1 i18n (gettext/`.po`), HTMX, Tailwind CSS v4.3.3 standalone CLI, django-unfold 0.43.0.

**Source spec:** `docs/superpowers/specs/2026-08-16-frontend-nord-i18n-design.md`

---

## Verified External Facts

Confirmed empirically while writing this plan. Do not re-derive; do not assume differently.

**Tailwind standalone CLI**
- Latest release: **v4.3.3**. Linux assets: `tailwindcss-linux-x64` (glibc), `tailwindcss-linux-x64-musl`, plus arm64 variants.
- Our base image is `python:3.12-slim` (Debian/glibc) → use **`tailwindcss-linux-x64`**.
- Pinned URL: `https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.3/tailwindcss-linux-x64`
- CLI flags confirmed via `--help`: `-i/--input`, `-o/--output`, `-w/--watch`, `-m/--minify`, `--cwd`.
- **v4 uses CSS-first config — there is no `tailwind.config.js`.** Verified working syntax:
  - `@import "tailwindcss";`
  - `@source "<path>";` — required to scan Django template dirs
  - `@custom-variant dark (&:where(.dark, .dark *));` — class-based dark mode
  - `@theme { --color-<name>: <value>; }` — generates `bg-<name>` / `text-<name>` utilities
- Verified by compiling a fixture: `bg-surface`, `text-accent`, `.dark` variant and `md:` breakpoints all generated; unused classes purged; 4.5 KB minified, 42 ms build.

**django-unfold 0.43.0 `COLORS` format**
- Shape is `{"primary": {...}, "font": {...}}`.
- Values are **space-separated RGB channels** (`"250 245 255"`), NOT hex and NOT comma-separated.
- `primary` requires all 11 shades: `50,100,200,300,400,500,600,700,800,900,950`.
- `font` keys: `subtle-light`, `subtle-dark`, `default-light`, `default-dark`, `important-light`, `important-dark`.

**Nord primary scale** (computed by anchoring Nord10 `#5E81AC` at shade 600):
```
50:245 247 250   100:231 237 243  200:208 218 231  300:174 192 213
400:141 165 196  500:114 144 182  600:93 129 172   700:75 106 145
800:59 84 114    900:47 67 91     950:31 44 61
```

**Measured WCAG ratios — the palette is NOT literal Nord, and that is deliberate.**
Literal Nord fails twice in dark mode (the default theme):
- Nord3 `#4C566A` muted text on Nord0 → **1.69** (needs ≥ 4.5)
- Nord11 `#BF616A` flagged-row text on Nord0 → **3.05**
- Also, Nord10 `#5E81AC` as light-mode link text → **3.50**

Verified accessible token set (every value ≥ 4.5 against both its base and raised surface):

| Token | Dark | Light |
|---|---|---|
| `--surface` | `#2E3440` | `#ECEFF4` |
| `--surface-raised` | `#3B4252` | `#FFFFFF` |
| `--border` | `#4C566A` | `#D8DEE9` |
| `--text` | `#ECEFF4` | `#2E3440` |
| `--text-muted` | `#ACB6C6` | `#434C5E` |
| `--accent` | `#88C0D0` | `#3F5A7D` |
| `--accent-contrast` | `#2E3440` | `#FFFFFF` |
| `--danger` | `#E0A0A6` | `#A54049` |
| `--danger-surface` | `#3A2C2E` | `#F7E4E6` |

**Existing data to migrate** (real values currently in `SnapshotItem`):
- `flag_reason`: `None`, `'Blacklisted'`, `'No rule configured'`, `'Could not be parsed'`
- `price_source`: `'Raven Special'` (a rule name), `'Blacklisted'`, `'No rule configured'`, `'none'`

---

## File Structure

```
eve-buyback/
├── Dockerfile                          # + Tailwind binary fetch, + CSS build
├── docker-compose.yml                  # + tailwind --watch sidecar
├── assets/css/input.css                # NEW: Tailwind entry + Nord tokens
├── static/css/app.css                  # NEW (generated, gitignored)
├── locale/                             # NEW: .po files
├── config/
│   ├── settings.py                     # + i18n, LOCALE_PATHS, UNFOLD COLORS
│   ├── urls.py                         # + i18n set_language
│   └── middleware.py                   # NEW: force English on /admin/
├── pricing/
│   ├── domain/resolution.py            # emit kind + rule name, not English
│   └── templatetags/                   # (none — filter lives in buyback)
├── buyback/
│   ├── domain/quote.py                 # + FlagReason enum
│   ├── models.py                       # field split
│   ├── migrations/0002_*.py            # schema
│   ├── migrations/0003_*.py            # data migration
│   ├── templatetags/buyback_labels.py  # NEW: key -> translated string
│   └── templates/buyback/*.html        # restyled + translated
├── templates/base.html                 # header, theme toggle, lang switcher
└── tests/
    ├── i18n/test_language_resolution.py
    ├── i18n/test_translation_boundary.py
    └── buyback/test_label_filter.py
```

**Percent/key convention reminder:** enum *values* are stable machine keys (`BLACKLISTED`), never displayed raw. Display always goes through the template filter.

---

## Task 1: Tailwind build pipeline

**Files:**
- Create: `assets/css/input.css`
- Modify: `Dockerfile`, `docker-compose.yml`, `.gitignore`

- [ ] **Step 1: Create `assets/css/input.css`**

`@source` paths are relative to this file. All four template locations must be listed or their classes get purged.

```css
/* source(none) disables Tailwind v4's automatic project-root scanning.
   Without it, Tailwind treats every file in the repo as a source — including
   docs/*.md, which contain the full template markup from this very plan. That
   was verified leaking: a class mentioned only in a markdown file was compiled
   into the shipped stylesheet, and output was 16.4 KB instead of 5.7 KB.
   With source(none), only the three directories declared below are scanned. */
@import "tailwindcss" source(none);

@source "../../templates";
@source "../../buyback/templates";
@source "../../pricing/templates";

/* Class-based dark mode: the root <html> carries .dark */
@custom-variant dark (&:where(.dark, .dark *));

/* Nord, expressed as semantic roles. Values are WCAG-AA verified —
   see the plan's Verified External Facts table. Literal Nord fails
   contrast for dark muted text, dark danger text, and light accent. */
:root {
  --surface: #ECEFF4;
  --surface-raised: #FFFFFF;
  --border: #D8DEE9;
  --text: #2E3440;
  --text-muted: #434C5E;
  --accent: #3F5A7D;
  --accent-contrast: #FFFFFF;
  --danger: #A54049;
  --danger-surface: #F7E4E6;
}

:root.dark {
  --surface: #2E3440;
  --surface-raised: #3B4252;
  --border: #4C566A;
  --text: #ECEFF4;
  --text-muted: #ACB6C6;
  --accent: #88C0D0;
  --accent-contrast: #2E3440;
  --danger: #E0A0A6;
  --danger-surface: #3A2C2E;
}

@theme {
  --color-surface: var(--surface);
  --color-surface-raised: var(--surface-raised);
  --color-border-token: var(--border);
  --color-text: var(--text);
  --color-text-muted: var(--text-muted);
  --color-accent: var(--accent);
  --color-accent-contrast: var(--accent-contrast);
  --color-danger: var(--danger);
  --color-danger-surface: var(--danger-surface);
}

body {
  background-color: var(--surface);
  color: var(--text);
}
```

- [ ] **Step 2: Add the Tailwind binary and CSS build to `Dockerfile`**

Insert after the `COPY requirements.txt` / `pip install` block and before `COPY . .`:

```dockerfile
# Tailwind standalone CLI — no Node required. Pinned; do not track "latest".
ARG TAILWIND_VERSION=v4.3.3
RUN curl -sL -o /usr/local/bin/tailwindcss \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    && chmod +x /usr/local/bin/tailwindcss
```

Then after `COPY . .`, and **before** the existing `collectstatic` line, add:

```dockerfile
RUN tailwindcss -i assets/css/input.css -o static/css/app.css --minify
```

Order matters: `collectstatic` must run after the CSS exists, or the built file never reaches `STATIC_ROOT`.

- [ ] **Step 3: Add the watch sidecar to `docker-compose.yml`**

Add as a new service alongside `web` and `db`:

```yaml
  tailwind:
    build: .
    command: tailwindcss -i assets/css/input.css -o static/css/app.css --watch
    volumes:
      - .:/app
    depends_on:
      - web
```

- [ ] **Step 4: Ignore the generated CSS**

Append to `.gitignore`:

```
static/css/app.css
```

- [ ] **Step 5: Build and verify the CSS actually compiles**

Run:
```bash
docker compose build web
docker compose run --rm --no-deps web tailwindcss -i assets/css/input.css -o /tmp/probe.css --minify
```
Expected: `Done in <N>ms` and no errors.

- [ ] **Step 6: Verify purging works and docs are not being scanned**

Do NOT probe with `bg-surface` or other `@theme` colours — measured behaviour: Tailwind v4 emits utilities for `@theme`-declared colours **unconditionally**, so their presence proves nothing about whether `@source` is wired. Probe with ordinary utilities instead.

Run:
```bash
echo 'class="bg-lime-300"' > docs/_probe.md
docker compose run --rm --no-deps web sh -c \
  'tailwindcss -i assets/css/input.css -o /tmp/probe.css >/dev/null 2>&1; \
   grep -q "bg-lime-300" /tmp/probe.css && echo "LEAK: docs scanned" || echo "ok: docs excluded"; \
   grep -q "\.rounded-lg" /tmp/probe.css && echo "BLOAT: unused utility present" || echo "ok: unused purged"; \
   wc -c /tmp/probe.css'
rm -f docs/_probe.md
```
Expected:
```
ok: docs excluded
ok: unused purged
<about 5-6 KB>
```

A `LEAK` result means `source(none)` is missing from `input.css`. A size near 16 KB means the same thing.

- [ ] **Step 6b: Confirm all three template directories are actually scanned**

Run:
```bash
printf '<div class="tabular-nums"></div>\n' >> templates/base.html
printf '<div class="overflow-x-auto"></div>\n' >> buyback/templates/buyback/form.html
printf '<div class="rounded-lg"></div>\n' >> pricing/templates/pricing/rule_summary.html
docker compose run --rm --no-deps web sh -c \
  'tailwindcss -i assets/css/input.css -o /tmp/probe.css >/dev/null 2>&1; \
   for c in tabular-nums overflow-x-auto rounded-lg; do \
     grep -q "\.$c" /tmp/probe.css && echo "FOUND $c" || echo "MISSING $c"; done'
git checkout templates/base.html buyback/templates/buyback/form.html pricing/templates/pricing/rule_summary.html
```
Expected: all three `FOUND`. Any `MISSING` means that directory's `@source` path is wrong.

- [ ] **Step 7: Commit**

```bash
git add assets Dockerfile docker-compose.yml .gitignore
git commit -m "Add Tailwind standalone build pipeline with Nord semantic tokens"
```

---

## Task 2: FlagReason enum and domain key emission

The domain cannot import Django, so it cannot translate. It emits keys.

**Files:**
- Modify: `buyback/domain/quote.py`, `pricing/domain/resolution.py`, `pricing/domain/decisions.py`
- Test: `tests/buyback/test_quote.py`, `tests/pricing/test_resolution.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/buyback/test_quote.py`:

```python
from buyback.domain.quote import FlagReason


def test_unrecognized_item_emits_key_not_english():
    result = appraisal(
        [AppraisalItem(type_id=99999, name="Mystery", quantity=1, unit_price=Decimal("10.00"))]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert quote.lines[0].flag_reason == FlagReason.UNRECOGNIZED
    assert quote.lines[0].flag_reason != "Unrecognized item"


def test_unparseable_line_emits_key_not_english():
    result = appraisal([], failures=["junk"])

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert quote.lines[0].flag_reason == FlagReason.UNPARSEABLE
```

Add to `tests/pricing/test_resolution.py`:

```python
def test_blacklist_emits_kind_and_no_rule_name():
    ruleset = build_ruleset(blacklist_type_ids=frozenset({587}))

    decision = resolve_price(RIFTER, ruleset, NOW)

    assert decision.source_kind is PriceSourceKind.BLACKLIST
    assert decision.rule_name == ""


def test_custom_rule_carries_its_name_untranslated():
    decision = resolve_price(RAVEN, build_ruleset(), NOW)

    assert decision.source_kind is PriceSourceKind.CUSTOM
    assert decision.rule_name == "Raven Special"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/buyback/test_quote.py tests/pricing/test_resolution.py -v`
Expected: FAIL — `ImportError: cannot import name 'FlagReason'` and `AttributeError: 'PriceDecision' object has no attribute 'rule_name'`.

- [ ] **Step 3: Replace `source_label` with `rule_name` in `pricing/domain/decisions.py`**

```python
@dataclass(frozen=True)
class PriceDecision:
    """The outcome of resolving one item against the rule set.

    `percent` is in percentage points: Decimal("80.00") means 80%.

    `source_kind` is a machine key for the *category* of rule that won.
    `rule_name` is the admin-authored name of the winning rule, and is
    empty for system sources. The two are separate because they need
    opposite treatment at render time: the kind is translated, the
    rule name never is — it is the operator's data, not UI text.
    """

    percent: Decimal
    source_kind: PriceSourceKind
    rule_name: str = ""
    flagged: bool = False
    flag_reason: "FlagReason | None" = None
```

Add to the same file, above `PriceDecision`:

```python
Also change `PriceSourceKind`'s values to UPPERCASE in the same file. They were
lowercase (`"blacklist"`), but they are persisted to `price_source_kind` and read
back by the Task 4 filter, which uses uppercase keys — and the Task 3 backfill
writes uppercase too. Left lowercase, every newly generated quote renders a blank
Source column while backfilled rows look correct:

```python
class PriceSourceKind(StrEnum):
    """Which category of rule set an item's price.

    Values are UPPERCASE because they are persisted and looked up by the
    presentation layer; they must match the backfill migration's keys and
    the template filter's keys.
    """

    BLACKLIST = "BLACKLIST"
    SALE = "SALE"
    CUSTOM = "CUSTOM"
    CATEGORY_DEFAULT = "CATEGORY_DEFAULT"
    NONE = "NONE"
```

```python
class FlagReason(StrEnum):
    """Why a line was rejected. A stable key — never displayed raw."""

    BLACKLISTED = "BLACKLISTED"
    NO_RULE = "NO_RULE"
    UNRECOGNIZED = "UNRECOGNIZED"
    UNPARSEABLE = "UNPARSEABLE"
```

- [ ] **Step 4: Update `pricing/domain/resolution.py` to emit keys**

Replace the four `PriceDecision(...)` constructions:

```python
    if ruleset.is_blacklisted(item):
        return PriceDecision(
            percent=ZERO,
            source_kind=PriceSourceKind.BLACKLIST,
            rule_name="",
            flagged=True,
            flag_reason=FlagReason.BLACKLISTED,
        )

    active_sales = tuple(rule for rule in ruleset.sales if rule.is_active(now))
    sale = _best_match(active_sales, item)
    if sale is not None:
        return PriceDecision(
            percent=sale.percent,
            source_kind=PriceSourceKind.SALE,
            rule_name=sale.label,
        )

    custom = _best_match(ruleset.custom_rules, item)
    if custom is not None:
        return PriceDecision(
            percent=custom.percent,
            source_kind=PriceSourceKind.CUSTOM,
            rule_name=custom.label,
        )

    default = ruleset.category_defaults.get(item.category_id)
    if default is not None:
        return PriceDecision(
            percent=default,
            source_kind=PriceSourceKind.CATEGORY_DEFAULT,
            rule_name="",
        )

    return PriceDecision(
        percent=ZERO,
        source_kind=PriceSourceKind.NONE,
        rule_name="",
        flagged=True,
        flag_reason=FlagReason.NO_RULE,
    )
```

Update the import at the top of the file:

```python
from pricing.domain.decisions import FlagReason, PriceDecision, PriceSourceKind
```

- [ ] **Step 5: Re-export `FlagReason` from `buyback/domain/quote.py`**

`FlagReason` lives in `pricing/domain/decisions.py` because `resolve_price` produces it, but `quote.py` also emits it for its own two cases. Add to `quote.py`'s imports and re-export so callers have one obvious place to get it:

```python
from pricing.domain.decisions import FlagReason, PriceSourceKind

__all__ = ["FlagReason", "Quote", "QuoteLine", "build_quote"]
```

- [ ] **Step 6: Update `QuoteLine` and `build_quote` in `buyback/domain/quote.py`**

Change the dataclass fields:

```python
@dataclass(frozen=True)
class QuoteLine:
    type_id: int | None
    type_name: str
    quantity: int
    unit_price: Decimal
    percent_applied: Decimal
    price_source_kind: str
    price_source_label: str
    line_total: Decimal
    is_flagged: bool
    flag_reason: FlagReason | None
```

In the unrecognized branch:

```python
            lines.append(
                QuoteLine(
                    type_id=item.type_id,
                    type_name=item.name[:MAX_TYPE_NAME_LENGTH],
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    percent_applied=Decimal("0"),
                    price_source_kind=PriceSourceKind.NONE.value,
                    price_source_label="",
                    line_total=ZERO_ISK,
                    is_flagged=True,
                    flag_reason=FlagReason.UNRECOGNIZED,
                )
            )
```

In the priced branch:

```python
        lines.append(
            QuoteLine(
                type_id=item.type_id,
                type_name=item.name[:MAX_TYPE_NAME_LENGTH],
                quantity=item.quantity,
                unit_price=item.unit_price,
                percent_applied=decision.percent,
                price_source_kind=decision.source_kind.value,
                price_source_label=decision.rule_name,
                line_total=total,
                is_flagged=decision.flagged,
                flag_reason=decision.flag_reason,
            )
        )
```

In the failures branch:

```python
        lines.append(
            QuoteLine(
                type_id=None,
                type_name=failure[:MAX_TYPE_NAME_LENGTH],
                quantity=0,
                unit_price=ZERO_ISK,
                percent_applied=Decimal("0"),
                price_source_kind=PriceSourceKind.NONE.value,
                price_source_label="",
                line_total=ZERO_ISK,
                is_flagged=True,
                flag_reason=FlagReason.UNPARSEABLE,
            )
        )
```

Delete the now-unused `NO_SOURCE_LABEL` constant.

- [ ] **Step 7: Update the existing assertions that expect English**

In `tests/buyback/test_quote.py`, replace assertions on the old fields:

```python
    assert rifter.is_flagged is True
    assert rifter.flag_reason == FlagReason.BLACKLISTED
    assert rifter.line_total == Decimal("0.00")
```

```python
    assert quote.lines[0].is_flagged is True
    assert quote.lines[0].flag_reason == FlagReason.NO_RULE
```

```python
    failure_line = quote.lines[-1]
    assert failure_line.type_name == "definitely not an item"
    assert failure_line.type_id is None
    assert failure_line.is_flagged is True
    assert failure_line.flag_reason == FlagReason.UNPARSEABLE
    assert failure_line.line_total == Decimal("0.00")
```

In `tests/pricing/test_resolution.py`, replace every `decision.source_label == "..."` with the equivalent `decision.rule_name == "..."`, and `source_label == "Blacklisted"` with `source_kind is PriceSourceKind.BLACKLIST`.

- [ ] **Step 8: Run the domain tests**

Run: `docker compose exec web pytest tests/pricing/ tests/buyback/test_quote.py -v`
Expected: PASS. Any failure here is a real signature mismatch — fix it rather than loosening the assertion.

- [ ] **Step 9: Verify the domain is still Django-free**

Run: `docker compose exec web sh -c 'grep -rnE "^\s*(from|import)\s+django" pricing/domain/ buyback/domain/ || echo CLEAN'`
Expected: `CLEAN`

- [ ] **Step 10: Commit**

```bash
git add pricing/domain buyback/domain tests/pricing tests/buyback/test_quote.py
git commit -m "Emit stable enum keys from the domain instead of English labels"
```

---

## Task 3: SnapshotItem field split and migrations

**Files:**
- Modify: `buyback/models.py`, `buyback/services.py`
- Create: `buyback/migrations/0002_split_snapshotitem_labels.py` (generated), `buyback/migrations/0003_backfill_snapshotitem_keys.py` (hand-written)
- Test: `tests/buyback/test_models.py`, `tests/buyback/test_migration_backfill.py`

- [ ] **Step 1: Write the failing model test**

Replace the existing `test_snapshot_items_preserve_resolved_values` in `tests/buyback/test_models.py`:

```python
@pytest.mark.django_db
def test_snapshot_items_store_kind_and_label_separately():
    snapshot = Snapshot.objects.create(code="4ovArs", total_value=Decimal("140.00"))
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=638,
        type_name="Raven",
        quantity=2,
        unit_price=Decimal("100.00"),
        percent_applied=Decimal("70.00"),
        price_source_kind="CUSTOM",
        price_source_label="Battleships",
        line_total=Decimal("140.00"),
    )

    item = snapshot.items.get()
    assert item.price_source_kind == "CUSTOM"
    assert item.price_source_label == "Battleships"
    assert item.flag_reason_code is None
    assert item.is_flagged is False


@pytest.mark.django_db
def test_system_source_has_no_rule_label():
    snapshot = Snapshot.objects.create(code="abc", total_value=Decimal("0.00"))
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=587,
        type_name="Rifter",
        quantity=1,
        unit_price=Decimal("50.00"),
        percent_applied=Decimal("0.00"),
        price_source_kind="BLACKLIST",
        price_source_label="",
        line_total=Decimal("0.00"),
        is_flagged=True,
        flag_reason_code="BLACKLISTED",
    )

    item = snapshot.items.get()
    assert item.price_source_label == ""
    assert item.flag_reason_code == "BLACKLISTED"
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_models.py -v`
Expected: FAIL with `TypeError: SnapshotItem() got unexpected keyword arguments: 'price_source_kind'`.

- [ ] **Step 3: Change the model fields in `buyback/models.py`**

Replace the `price_source` and `flag_reason` field definitions on `SnapshotItem`:

```python
    price_source_kind = models.CharField(
        max_length=32,
        help_text="Machine key for which category of rule won. Translated at render.",
    )
    price_source_label = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Admin-authored rule name. Never translated — it is data, not UI.",
    )
    flag_reason_code = models.CharField(
        max_length=32, null=True, blank=True,
        help_text="Machine key for why the line was rejected. Translated at render.",
    )
```

- [ ] **Step 4: Generate the schema migration**

Run:
```bash
docker compose exec web python manage.py makemigrations buyback --name split_snapshotitem_labels
```
Expected: creates `buyback/migrations/0002_split_snapshotitem_labels.py`.

Django will prompt about removing `price_source`/`flag_reason` and adding new non-null fields. Provide `""` as the one-off default for `price_source_kind` if asked. **Do not delete the old columns in this migration** — the backfill in Step 5 needs to read them. If the generated migration removes them, split it: keep only the `AddField` operations in `0002`, and move the two `RemoveField` operations into a new `0004_drop_legacy_label_columns.py` created after the backfill.

- [ ] **Step 5: Write the data migration `buyback/migrations/0003_backfill_snapshotitem_keys.py`**

```python
"""Backfill machine keys from the legacy English display strings.

The legacy `price_source` column held EITHER a system label OR an
admin-authored rule name, with no way to tell them apart. Anything not
matching a known system label is therefore treated as a rule name — which
is the correct reading, since system labels were a closed set.

Unrecognised values degrade to NONE/null rather than failing the migration:
losing a label is recoverable, refusing to migrate a frozen snapshot is not.
"""

from django.db import migrations

SOURCE_KIND_BY_LEGACY = {
    "Blacklisted": "BLACKLIST",
    "No rule configured": "NONE",
    "none": "NONE",
    "Category default": "CATEGORY_DEFAULT",
}

FLAG_CODE_BY_LEGACY = {
    "Blacklisted": "BLACKLISTED",
    "No rule configured": "NO_RULE",
    "Unrecognized item": "UNRECOGNIZED",
    "Could not be parsed": "UNPARSEABLE",
}


def forwards(apps, schema_editor):
    SnapshotItem = apps.get_model("buyback", "SnapshotItem")
    for item in SnapshotItem.objects.all().iterator():
        legacy_source = item.price_source or ""
        kind = SOURCE_KIND_BY_LEGACY.get(legacy_source)
        if kind is None:
            # Not a known system label, so it is an admin-authored rule name.
            item.price_source_kind = "CUSTOM"
            item.price_source_label = legacy_source
        else:
            item.price_source_kind = kind
            item.price_source_label = ""

        item.flag_reason_code = FLAG_CODE_BY_LEGACY.get(item.flag_reason)
        item.save(
            update_fields=[
                "price_source_kind", "price_source_label", "flag_reason_code"
            ]
        )


def backwards(apps, schema_editor):
    SnapshotItem = apps.get_model("buyback", "SnapshotItem")
    legacy_by_kind = {v: k for k, v in SOURCE_KIND_BY_LEGACY.items()}
    legacy_by_code = {v: k for k, v in FLAG_CODE_BY_LEGACY.items()}
    for item in SnapshotItem.objects.all().iterator():
        if item.price_source_kind in ("CUSTOM", "SALE") and item.price_source_label:
            item.price_source = item.price_source_label
        else:
            item.price_source = legacy_by_kind.get(item.price_source_kind, "none")
        item.flag_reason = legacy_by_code.get(item.flag_reason_code)
        item.save(update_fields=["price_source", "flag_reason"])


class Migration(migrations.Migration):
    dependencies = [("buyback", "0002_split_snapshotitem_labels")]
    operations = [migrations.RunPython(forwards, backwards)]
```

- [ ] **Step 6: Write a test for the backfill mapping**

Create `tests/buyback/test_migration_backfill.py`. This tests the mapping functions directly rather than running the migration, so it stays fast and does not need `django_test_migrations`:

```python
# tests/buyback/test_migration_backfill.py
import importlib

# A module name starting with a digit cannot be imported with a plain
# `import` statement, so load it by name instead.
backfill = importlib.import_module(
    "buyback.migrations.0003_backfill_snapshotitem_keys"
)


def test_known_system_labels_map_to_kinds():
    assert backfill.SOURCE_KIND_BY_LEGACY["Blacklisted"] == "BLACKLIST"
    assert backfill.SOURCE_KIND_BY_LEGACY["No rule configured"] == "NONE"
    assert backfill.SOURCE_KIND_BY_LEGACY["none"] == "NONE"


def test_known_flag_reasons_map_to_codes():
    assert backfill.FLAG_CODE_BY_LEGACY["Blacklisted"] == "BLACKLISTED"
    assert backfill.FLAG_CODE_BY_LEGACY["Could not be parsed"] == "UNPARSEABLE"
    assert backfill.FLAG_CODE_BY_LEGACY["Unrecognized item"] == "UNRECOGNIZED"


def test_rule_names_are_not_in_the_system_label_map():
    """A rule name must fall through to the CUSTOM branch, not match a key."""
    assert "Raven Special" not in backfill.SOURCE_KIND_BY_LEGACY
    assert "Battleships" not in backfill.SOURCE_KIND_BY_LEGACY
```

Note: a module name starting with a digit cannot be imported with a plain `import` statement, which is why `importlib.import_module` is used.

- [ ] **Step 7: Update `buyback/services.py` to write the new fields**

In `generate_snapshot`, change the `SnapshotItem(...)` construction inside `bulk_create`:

```python
            SnapshotItem(
                snapshot=snapshot,
                type_id=line.type_id,
                type_name=line.type_name,
                quantity=line.quantity,
                unit_price=line.unit_price,
                percent_applied=line.percent_applied,
                price_source_kind=line.price_source_kind,
                price_source_label=line.price_source_label,
                line_total=line.line_total,
                is_flagged=line.is_flagged,
                flag_reason_code=line.flag_reason.value if line.flag_reason else None,
            )
```

- [ ] **Step 8: Apply the migrations against the real database**

Run:
```bash
docker compose exec web python manage.py migrate buyback
docker compose exec web python manage.py shell -c "
from buyback.models import SnapshotItem
for i in SnapshotItem.objects.all():
    print(i.type_name, '|', i.price_source_kind, '|', repr(i.price_source_label), '|', i.flag_reason_code)
"
```
Expected: every row has a non-empty `price_source_kind`; the row whose legacy source was `Raven Special` shows `CUSTOM | 'Raven Special' | None`; blacklisted rows show `BLACKLIST | '' | BLACKLISTED`.

- [ ] **Step 9: Run the full suite**

Run: `docker compose exec web pytest -v`
Expected: PASS. `tests/buyback/test_services.py` and `tests/buyback/test_views.py` assertions referencing `price_source`/`flag_reason` must be updated to the new field names — update them, do not delete them.

- [ ] **Step 10: Commit**

```bash
git add buyback tests/buyback
git commit -m "Split SnapshotItem labels into machine keys and rule names"
```

---

## Task 4: Label translation filter

**Files:**
- Create: `buyback/templatetags/__init__.py`, `buyback/templatetags/buyback_labels.py`
- Test: `tests/buyback/test_label_filter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/buyback/test_label_filter.py
from buyback.templatetags.buyback_labels import flag_reason_label, price_source_label


class FakeItem:
    def __init__(self, kind="", label="", code=None):
        self.price_source_kind = kind
        self.price_source_label = label
        self.flag_reason_code = code


def test_rule_name_is_shown_verbatim_for_custom_and_sale():
    assert price_source_label(FakeItem("CUSTOM", "Raven Special")) == "Raven Special"
    assert price_source_label(FakeItem("SALE", "Summer")) == "Summer"


def test_system_kinds_render_translatable_text_not_the_raw_key():
    rendered = price_source_label(FakeItem("BLACKLIST", ""))

    assert rendered != "BLACKLIST"
    assert rendered == "Blacklisted"


def test_category_default_and_none_have_labels():
    assert price_source_label(FakeItem("CATEGORY_DEFAULT", "")) == "Category default"
    assert price_source_label(FakeItem("NONE", "")) == "—"


def test_unknown_kind_degrades_to_dash_rather_than_raising():
    assert price_source_label(FakeItem("WAT", "")) == "—"


def test_flag_reason_codes_render_text():
    assert flag_reason_label(FakeItem(code="BLACKLISTED")) == "Blacklisted"
    assert flag_reason_label(FakeItem(code="UNPARSEABLE")) == "Could not be parsed"
    assert flag_reason_label(FakeItem(code="UNRECOGNIZED")) == "Unrecognized item"
    assert flag_reason_label(FakeItem(code="NO_RULE")) == "No rule configured"


def test_absent_flag_reason_renders_empty():
    assert flag_reason_label(FakeItem(code=None)) == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_label_filter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'buyback.templatetags'`.

- [ ] **Step 3: Create `buyback/templatetags/__init__.py`** (empty file)

- [ ] **Step 4: Write `buyback/templatetags/buyback_labels.py`**

```python
"""Render stored machine keys as translated text.

This is the ONLY place keys become human-readable. The rule that matters:
a rule's name is the operator's data and is printed verbatim, while a
system source kind is buyback's own UI text and is translated. Item names
come from EVE via Janice and are never touched here at all.
"""

from django import template
from django.utils.translation import gettext_lazy as _

register = template.Library()

NO_LABEL = "—"

SOURCE_KIND_LABELS = {
    "BLACKLIST": _("Blacklisted"),
    "CATEGORY_DEFAULT": _("Category default"),
    "NONE": NO_LABEL,
}

FLAG_REASON_LABELS = {
    "BLACKLISTED": _("Blacklisted"),
    "NO_RULE": _("No rule configured"),
    "UNRECOGNIZED": _("Unrecognized item"),
    "UNPARSEABLE": _("Could not be parsed"),
}

# Kinds whose display value is the admin-authored rule name, not a translation.
NAMED_KINDS = frozenset({"CUSTOM", "SALE"})


@register.filter
def price_source_label(item) -> str:
    kind = getattr(item, "price_source_kind", "") or ""
    if kind in NAMED_KINDS:
        return getattr(item, "price_source_label", "") or NO_LABEL
    return str(SOURCE_KIND_LABELS.get(kind, NO_LABEL))


@register.filter
def flag_reason_label(item) -> str:
    code = getattr(item, "flag_reason_code", None)
    if not code:
        return ""
    return str(FLAG_REASON_LABELS.get(code, ""))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/buyback/test_label_filter.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add buyback/templatetags tests/buyback/test_label_filter.py
git commit -m "Add filter translating stored keys while preserving rule names"
```

---

## Task 5: Django i18n configuration and admin-English middleware

**Files:**
- Modify: `config/settings.py`, `config/urls.py`
- Create: `config/middleware.py`, `locale/.gitkeep`
- Test: `tests/i18n/__init__.py`, `tests/i18n/test_language_resolution.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/i18n/test_language_resolution.py
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_default_is_english_with_no_signal(client):
    response = client.get(reverse("buyback:form"))

    assert response.status_code == 200
    assert response.headers.get("Content-Language", "en").startswith("en")


@pytest.mark.django_db
def test_unknown_accept_language_falls_back_to_english(client):
    response = client.get(reverse("buyback:form"), HTTP_ACCEPT_LANGUAGE="xx-YY,zz")

    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_renders_english_even_with_a_non_english_cookie(client, django_user_model):
    django_user_model.objects.create_superuser("admin", "a@example.com", "pw12345678")
    client.login(username="admin", password="pw12345678")
    client.cookies["django_language"] = "de"

    response = client.get("/admin/")

    assert response.status_code == 200
    # The admin's own chrome must stay English regardless of the visitor's choice.
    assert b"Site administration" in response.content or b"Dashboard" in response.content


@pytest.mark.django_db
def test_set_language_view_is_reachable(client):
    response = client.post(
        "/i18n/setlang/", {"language": "en", "next": reverse("buyback:form")}
    )

    assert response.status_code in (302, 200)
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec web pytest tests/i18n/ -v`
Expected: FAIL — the `tests/i18n` package does not exist, and `/i18n/setlang/` 404s.

Create the package first so the tests can be collected:
```bash
mkdir -p tests/i18n && touch tests/i18n/__init__.py
mkdir -p locale && touch locale/.gitkeep
```

- [ ] **Step 3: Add i18n settings to `config/settings.py`**

Replace the existing `LANGUAGE_CODE` line and add below it:

```python
LANGUAGE_CODE = "en"
USE_I18N = True
USE_TZ = True

# Only English ships today. Adding a locale is a directory under locale/
# plus a translation pass — no code change required.
LANGUAGES = [
    ("en", "English"),
]

LOCALE_PATHS = [BASE_DIR / "locale"]
```

Add `LocaleMiddleware` to `MIDDLEWARE`, immediately after `SessionMiddleware` and before `CommonMiddleware` (Django requires this ordering), followed by our admin-English middleware:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "config.middleware.AdminEnglishMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

- [ ] **Step 4: Write `config/middleware.py`**

```python
"""Keep the admin in English regardless of the visitor's language choice.

LocaleMiddleware would otherwise translate the Django admin and Unfold
automatically. Translation is scoped to the public site by product decision,
so this re-activates English for anything under /admin/ — including the
rule summary page, which is rendered inside the admin shell.
"""

from django.utils import translation

ADMIN_PREFIX = "/admin/"


class AdminEnglishMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(ADMIN_PREFIX):
            translation.activate("en")
            request.LANGUAGE_CODE = "en"
        return self.get_response(request)
```

- [ ] **Step 5: Wire `set_language` into `config/urls.py`**

Add the i18n URLs before the admin include:

```python
from django.contrib import admin
from django.urls import include, path

from pricing.views import rule_summary

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/pricing/summary/", admin.site.admin_view(rule_summary), name="pricing_summary"),
    path("admin/", admin.site.urls),
    path("", include("buyback.urls")),
]
```

- [ ] **Step 6: Run the tests**

Run: `docker compose exec web pytest tests/i18n/ -v`
Expected: all 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add config tests/i18n locale
git commit -m "Configure Django i18n with English-only admin"
```

---

## Task 6: Translation boundary test with a pseudo-locale

Because only English ships, the pipeline would otherwise be untested — extraction and activation can break silently. This task proves the machinery with a test-only locale.

**Files:**
- Create: `tests/i18n/test_translation_boundary.py`

**`config/settings.py` is deliberately NOT modified.** `LANGUAGES` stays `[("en", "English")]` in production — adding the pseudo-locale there would put an "Esperanto" entry in the real switcher dropdown, offering visitors a locale with one translated string. The tests widen `LANGUAGES` locally via `override_settings` instead, so the fixture never escapes the test suite.

Note the two activation paths behave differently, which is why only one test needs the override:
- `translation.override("eo")` activates directly and does not consult `LANGUAGES`
- A `django_language` cookie goes through `LocaleMiddleware`, which *does* check `LANGUAGES`

- [ ] **Step 1: Write the failing test**

```python
# tests/i18n/test_translation_boundary.py
from decimal import Decimal

import pytest
from django.test import Client
from django.test.utils import override_settings
from django.utils import translation

from buyback.models import Snapshot, SnapshotItem
from buyback.templatetags.buyback_labels import flag_reason_label, price_source_label


class FakeItem:
    def __init__(self, kind="", label="", code=None):
        self.price_source_kind = kind
        self.price_source_label = label
        self.flag_reason_code = code


def test_system_label_changes_under_an_active_locale():
    with translation.override("eo"):
        translated = price_source_label(FakeItem("BLACKLIST", ""))

    with translation.override("en"):
        english = price_source_label(FakeItem("BLACKLIST", ""))

    assert english == "Blacklisted"
    assert translated == "Malpermesita"
    assert translated != english


def test_rule_name_is_identical_in_every_locale():
    """Admin-authored names are data, not UI. They must never translate."""
    with translation.override("eo"):
        translated = price_source_label(FakeItem("CUSTOM", "Raven Special"))
    with translation.override("en"):
        english = price_source_label(FakeItem("CUSTOM", "Raven Special"))

    assert translated == english == "Raven Special"


@pytest.mark.django_db
def test_eve_item_names_are_never_translated_on_the_quote_page():
    snapshot = Snapshot.objects.create(
        code="I18NTEST", total_value=Decimal("100.00"), contract_to="Corp"
    )
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=638,
        type_name="Raven",
        quantity=1,
        unit_price=Decimal("100.00"),
        percent_applied=Decimal("100.00"),
        price_source_kind="CUSTOM",
        price_source_label="Raven Special",
        line_total=Decimal("100.00"),
    )
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=587,
        type_name="Rifter",
        quantity=1,
        unit_price=Decimal("0.00"),
        percent_applied=Decimal("0.00"),
        price_source_kind="BLACKLIST",
        price_source_label="",
        line_total=Decimal("0.00"),
        is_flagged=True,
        flag_reason_code="BLACKLISTED",
    )

    # LANGUAGES is widened only here: LocaleMiddleware refuses to activate a
    # locale that is not configured, and production ships English alone.
    with override_settings(
        ALLOWED_HOSTS=["testserver"],
        LANGUAGES=[("en", "English"), ("eo", "Esperanto")],
    ):
        client = Client()
        client.cookies["django_language"] = "eo"
        body = client.get("/quote/I18NTEST/").content.decode()

    # EVE data and the operator's rule name survive verbatim...
    assert "Raven" in body
    assert "Raven Special" in body
    # ...while buyback's own label is translated.
    assert "Malpermesita" in body


@pytest.mark.django_db
def test_production_languages_offers_english_only(settings):
    """Guard: the pseudo-locale must never leak into the shipped switcher."""
    assert [code for code, _name in settings.LANGUAGES] == ["en"]
```

- [ ] **Step 2: Create the pseudo-locale translation**

Run:
```bash
docker compose exec web python manage.py makemessages -l eo --ignore=node_modules
```
Expected: creates `locale/eo/LC_MESSAGES/django.po` containing the strings wrapped in Task 4 and Task 7.

Then edit `locale/eo/LC_MESSAGES/django.po` and fill in exactly one entry so the boundary test has something to assert:

```po
msgid "Blacklisted"
msgstr "Malpermesita"
```

Leave the remaining `msgstr` values empty — untranslated strings correctly fall back to English, which is itself part of what this test verifies.

- [ ] **Step 3: Compile the messages**

Run:
```bash
docker compose exec web python manage.py compilemessages
```
Expected: `processing file django.po in .../locale/eo/LC_MESSAGES`.

If this fails with `gettext` not found, add to the `Dockerfile`'s apt install line: `gettext`. The existing line already installs `curl`; extend it to `curl gettext`, then rebuild.

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web pytest tests/i18n/ -v`
Expected: all tests PASS, including the three new boundary tests.

- [ ] **Step 5: Commit**

```bash
git add locale config/settings.py tests/i18n/test_translation_boundary.py
git commit -m "Prove the translation boundary with a test-only pseudo-locale"
```

---

## Task 7: Restyle the public templates

**Files:**
- Modify: `templates/base.html`, `buyback/templates/buyback/form.html`, `buyback/templates/buyback/snapshot.html`, `buyback/templates/buyback/_error.html`
- Test: `tests/buyback/test_views.py`

- [ ] **Step 1: Rewrite `templates/base.html`**

The inline script must run before first paint or the page flashes the wrong theme.

```html
{% load i18n static %}<!DOCTYPE html>
<html lang="{{ LANGUAGE_CODE|default:'en' }}">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}{% translate "EVE Buyback" %}{% endblock %}</title>

    <script>
      // Runs before first paint: follow the OS preference, fall back to dark,
      // and let an explicit stored choice win. Any later than this and the
      // page visibly flashes the wrong theme.
      (function () {
        var stored = null;
        try { stored = localStorage.getItem("theme"); } catch (e) {}
        var prefersLight = window.matchMedia &&
          window.matchMedia("(prefers-color-scheme: light)").matches;
        var dark = stored ? stored === "dark" : !prefersLight;
        document.documentElement.classList.toggle("dark", dark);
      })();
    </script>

    <link rel="stylesheet" href="{% static 'css/app.css' %}">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  </head>
  <body class="bg-surface text-text antialiased">
    <div class="mx-auto max-w-5xl px-4 py-8">
      <header class="mb-8 flex items-center justify-between gap-4 border-b border-border-token pb-4">
        <a href="{% url 'buyback:form' %}"
           class="text-xl font-semibold tracking-tight text-text no-underline">
          {% translate "EVE Buyback" %}
        </a>

        <div class="flex items-center gap-3">
          {% if LANGUAGES|length > 1 %}
            <form action="{% url 'set_language' %}" method="post"
                  hx-post="{% url 'set_language' %}" hx-target="body" hx-swap="outerHTML">
              {% csrf_token %}
              <input type="hidden" name="next" value="{{ request.path }}">
              <label class="sr-only" for="lang">{% translate "Language" %}</label>
              <select id="lang" name="language" onchange="this.form.requestSubmit()"
                      class="rounded-md border border-border-token bg-surface-raised px-2 py-1
                             text-sm text-text">
                {% get_current_language as CURRENT %}
                {% for code, name in LANGUAGES %}
                  <option value="{{ code }}" {% if code == CURRENT %}selected{% endif %}>
                    {{ name }}
                  </option>
                {% endfor %}
              </select>
            </form>
          {% endif %}

          <button type="button" id="theme-toggle"
                  aria-label="{% translate 'Toggle colour theme' %}"
                  class="rounded-md border border-border-token bg-surface-raised px-3 py-1
                         text-sm text-text hover:text-accent">
            <span class="dark:hidden">☾</span>
            <span class="hidden dark:inline">☀</span>
          </button>
        </div>
      </header>

      <main>{% block content %}{% endblock %}</main>
    </div>

    <script>
      document.getElementById("theme-toggle").addEventListener("click", function () {
        var dark = document.documentElement.classList.toggle("dark");
        try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch (e) {}
      });
    </script>
  </body>
</html>
```

- [ ] **Step 2: Rewrite `buyback/templates/buyback/form.html`**

```html
{% extends "base.html" %}
{% load i18n %}

{% block content %}
  <p class="mb-4 text-text-muted">
    {% translate "Paste your items below (copy from your in-game inventory) to get a buyback quote." %}
  </p>

  <div id="result"></div>

  <form hx-post="{% url 'buyback:submit' %}" hx-target="#result" hx-swap="innerHTML"
        class="mt-4">
    {% csrf_token %}
    <textarea name="raw_text" rows="12"
              placeholder="{% translate 'Raven	1' %}&#10;{% translate 'Tritanium	1000' %}"
              class="w-full rounded-lg border border-border-token bg-surface-raised p-3
                     font-mono text-sm text-text placeholder:text-text-muted
                     focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"></textarea>
    <button type="submit"
            class="mt-4 rounded-lg bg-accent px-5 py-2 font-medium text-accent-contrast
                   hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-accent">
      {% translate "Get quote" %}
    </button>
  </form>

  {% if config.contract_to %}
    <p class="mt-6 text-sm text-text-muted">
      {% blocktranslate with corp=config.contract_to %}Accepted contracts go to <strong>{{ corp }}</strong>.{% endblocktranslate %}
    </p>
  {% endif %}
{% endblock %}
```

- [ ] **Step 3: Rewrite `buyback/templates/buyback/snapshot.html`**

```html
{% extends "base.html" %}
{% load i18n buyback_labels %}

{% block title %}{% blocktranslate with code=snapshot.code %}Quote {{ code }}{% endblocktranslate %}{% endblock %}

{% block content %}
  <h2 class="text-2xl font-semibold tracking-tight">
    {% blocktranslate with code=snapshot.code %}Quote {{ code }}{% endblocktranslate %}
  </h2>

  <p class="mt-2 text-sm text-text-muted">
    {% blocktranslate with created=snapshot.created_at %}Generated {{ created }}. This page is permanent and will not change.{% endblocktranslate %}
    <a href="{{ snapshot.janice_url }}" class="text-accent underline">{{ snapshot.janice_url }}</a>
  </p>

  <div class="mt-6 overflow-x-auto rounded-lg border border-border-token">
    <table class="w-full border-collapse text-sm">
      <thead class="bg-surface-raised">
        <tr>
          <th class="px-3 py-2 text-left font-medium">{% translate "Item" %}</th>
          <th class="px-3 py-2 text-right font-medium">{% translate "Qty" %}</th>
          <th class="px-3 py-2 text-right font-medium">{% translate "Unit price" %}</th>
          <th class="px-3 py-2 text-right font-medium">{% translate "Rate" %}</th>
          <th class="px-3 py-2 text-left font-medium">{% translate "Source" %}</th>
          <th class="px-3 py-2 text-right font-medium">{% translate "Total" %}</th>
        </tr>
      </thead>
      <tbody>
        {% for item in snapshot.items.all %}
          <tr class="border-t border-border-token {% if item.is_flagged %}bg-danger-surface{% endif %}">
            <td class="px-3 py-2 {% if item.is_flagged %}text-danger{% endif %}">
              {{ item.type_name }}
              {% if item.is_flagged %}
                <div class="text-xs">{{ item|flag_reason_label }}</div>
              {% endif %}
            </td>
            <td class="px-3 py-2 text-right tabular-nums">{{ item.quantity }}</td>
            <td class="px-3 py-2 text-right tabular-nums">{{ item.unit_price }}</td>
            <td class="px-3 py-2 text-right tabular-nums">{{ item.percent_applied }}%</td>
            <td class="px-3 py-2 text-text-muted">{{ item|price_source_label }}</td>
            <td class="px-3 py-2 text-right tabular-nums">{{ item.line_total }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <p class="mt-6 text-2xl font-bold tabular-nums">
    {% blocktranslate with total=snapshot.total_value %}Total offer: {{ total }} ISK{% endblocktranslate %}
  </p>

  {% if snapshot.contract_to %}
    <div class="mt-8 rounded-lg border border-border-token bg-surface-raised p-4">
      <h3 class="font-semibold">{% translate "How to sell" %}</h3>
      <p class="mt-2 text-sm">
        {% blocktranslate with corp=snapshot.contract_to %}Create an in-game contract to <strong>{{ corp }}</strong>.{% endblocktranslate %}
      </p>
      {% if snapshot.contract_instructions %}
        <p class="mt-2 text-sm text-text-muted">{{ snapshot.contract_instructions|linebreaksbr }}</p>
      {% endif %}
    </div>
  {% endif %}
{% endblock %}
```

- [ ] **Step 4: Rewrite `buyback/templates/buyback/_error.html`**

```html
<div class="rounded-lg border border-danger bg-danger-surface px-4 py-3 text-danger">
  {{ message }}
</div>
```

- [ ] **Step 5: Rebuild the CSS and confirm the utilities are now generated**

Run:
```bash
docker compose exec web tailwindcss -i assets/css/input.css -o static/css/app.css --minify
docker compose exec web sh -c \
  'for c in tabular-nums overflow-x-auto bg-danger-surface antialiased; do
     grep -q "\.$c" static/css/app.css && echo "FOUND $c" || echo "MISSING $c"; done
   wc -c static/css/app.css'
```
Expected: all four `FOUND`, because the templates you just wrote use them. These are ordinary utilities, not `@theme` colours — `@theme` colours emit unconditionally and so cannot tell you whether `@source` worked.

Also re-confirm docs are still excluded now that more markup exists:
```bash
echo 'class="bg-lime-300"' > docs/_probe.md
docker compose exec web sh -c \
  'tailwindcss -i assets/css/input.css -o /tmp/probe.css >/dev/null 2>&1; \
   grep -q "bg-lime-300" /tmp/probe.css && echo "LEAK" || echo "ok: docs excluded"'
rm -f docs/_probe.md
```
Expected: `ok: docs excluded`

- [ ] **Step 6: Verify the pages still render and escaping still holds**

Run:
```bash
docker compose exec -T web python manage.py shell -c "
from django.test import Client
from django.test.utils import override_settings
with override_settings(ALLOWED_HOSTS=['testserver']):
    c = Client()
    print('form:', c.get('/').status_code)
"
```
Expected: `form: 200`

- [ ] **Step 7: Run the full suite**

Run: `docker compose exec web pytest -v`
Expected: PASS. Update any assertion in `tests/buyback/test_views.py` that matched old markup — e.g. a test asserting `b"Blacklisted" in body` still works, but one matching the old inline `class="flagged"` needs updating to `bg-danger-surface`.

- [ ] **Step 8: Commit**

```bash
git add templates buyback/templates tests/buyback/test_views.py static
git commit -m "Restyle public templates with Nord tokens and translation tags"
```

---

## Task 8: Restyle the rule summary page and tint the admin

The rule summary lives in the admin shell, so it gets the Nord restyle but stays English.

**Files:**
- Modify: `pricing/templates/pricing/rule_summary.html`, `config/settings.py`
- Test: `tests/pricing/test_summary_view.py`

- [ ] **Step 1: Rewrite `pricing/templates/pricing/rule_summary.html`**

No `{% translate %}` here — the admin stays English by product decision.

```html
{% extends "admin/base_site.html" %}

{% block content %}
  <h1>Rule summary</h1>
  <p style="color:#6b7280;max-width:60ch">
    Ordered by precedence: blacklist beats sales, sales beat custom rules,
    custom rules beat category defaults. Within a tier, the most specific
    match wins.
  </p>

  <div style="overflow-x:auto;border:1px solid #d8dee9;border-radius:8px;margin-top:1rem">
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead style="background:#eceff4">
        <tr>
          <th style="text-align:left;padding:8px 12px">Tier</th>
          <th style="text-align:left;padding:8px 12px">Rule</th>
          <th style="text-align:left;padding:8px 12px">Level</th>
          <th style="text-align:left;padding:8px 12px">Targets</th>
          <th style="text-align:right;padding:8px 12px">Percent</th>
          <th style="text-align:left;padding:8px 12px">Status</th>
          <th style="text-align:left;padding:8px 12px">Window</th>
        </tr>
      </thead>
      <tbody>
        {% for row in rows %}
          <tr style="border-top:1px solid #d8dee9">
            <td style="padding:8px 12px">{{ row.kind }}</td>
            <td style="padding:8px 12px">{{ row.label }}</td>
            <td style="padding:8px 12px">{{ row.level }}</td>
            <td style="padding:8px 12px">{{ row.targets|join:", "|truncatechars:80 }}</td>
            <td style="padding:8px 12px;text-align:right">
              {% if row.percent is not None %}{{ row.percent }}%{% else %}—{% endif %}
            </td>
            <td style="padding:8px 12px">{{ row.status }}</td>
            <td style="padding:8px 12px">{{ row.window }}</td>
          </tr>
        {% empty %}
          <tr><td colspan="7" style="padding:12px">No rules configured yet.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% endblock %}
```

Inline styles are used deliberately here rather than Tailwind classes: this template extends the admin's own base, which does not load `app.css`, so Tailwind utilities would not resolve.

- [ ] **Step 2: Tint Unfold toward Nord in `config/settings.py`**

Add inside the existing `UNFOLD` dict. Values are space-separated RGB channels — Unfold's format, verified against version 0.43.0. Shade 600 is Nord10 `#5E81AC`.

```python
    "COLORS": {
        "primary": {
            "50": "245 247 250",
            "100": "231 237 243",
            "200": "208 218 231",
            "300": "174 192 213",
            "400": "141 165 196",
            "500": "114 144 182",
            "600": "93 129 172",
            "700": "75 106 145",
            "800": "59 84 114",
            "900": "47 67 91",
            "950": "31 44 61",
        },
    },
```

- [ ] **Step 3: Verify the admin and summary page still render**

Run:
```bash
docker compose exec -T web pytest tests/pricing/test_summary_view.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 4: Confirm the admin still renders English**

Run:
```bash
docker compose exec -T web pytest tests/i18n/test_language_resolution.py -v
```
Expected: PASS, including `test_admin_renders_english_even_with_a_non_english_cookie`.

- [ ] **Step 5: Commit**

```bash
git add pricing/templates config/settings.py
git commit -m "Restyle rule summary and tint Unfold admin toward Nord"
```

---

## Task 9: Full verification

No new code — this proves the assembled feature works.

- [ ] **Step 1: Rebuild the image from scratch**

Run:
```bash
docker compose build --no-cache web
docker compose up -d
docker compose exec web python manage.py migrate
```
Expected: build succeeds, including the Tailwind fetch and CSS build.

- [ ] **Step 2: Confirm the CSS was built into the image and collected**

Run:
```bash
docker compose exec web sh -c 'wc -c static/css/app.css && wc -c staticfiles/css/app.css'
```
Expected: both non-zero. If `staticfiles/` is missing the file, `collectstatic` ran before the Tailwind build — fix the `Dockerfile` ordering.

- [ ] **Step 3: Run the full suite**

Run: `docker compose exec web pytest -v`
Expected: all tests pass. Record the count.

- [ ] **Step 4: Verify theme behaviour without JavaScript**

Run:
```bash
docker compose exec -T web python manage.py shell -c "
from django.test import Client
from django.test.utils import override_settings
with override_settings(ALLOWED_HOSTS=['testserver']):
    body = Client().get('/').content.decode()
print('pre-paint script present:', 'prefers-color-scheme' in body)
print('stylesheet linked      :', 'css/app.css' in body)
print('toggle present         :', 'theme-toggle' in body)
"
```
Expected: all three `True`.

- [ ] **Step 5: Verify the translation boundary end to end**

Run:
```bash
docker compose exec -T web python manage.py shell -c "
from decimal import Decimal
from django.test import Client
from django.test.utils import override_settings
from buyback.models import Snapshot, SnapshotItem
Snapshot.objects.filter(code='E2E18N').delete()
s = Snapshot.objects.create(code='E2E18N', total_value=Decimal('100.00'), contract_to='Corp')
SnapshotItem.objects.create(snapshot=s, type_id=638, type_name='Raven', quantity=1,
    unit_price=Decimal('100.00'), percent_applied=Decimal('100.00'),
    price_source_kind='CUSTOM', price_source_label='Raven Special',
    line_total=Decimal('100.00'))
SnapshotItem.objects.create(snapshot=s, type_id=587, type_name='Rifter', quantity=1,
    unit_price=Decimal('0.00'), percent_applied=Decimal('0.00'),
    price_source_kind='BLACKLIST', price_source_label='',
    line_total=Decimal('0.00'), is_flagged=True, flag_reason_code='BLACKLISTED')
with override_settings(ALLOWED_HOSTS=['testserver']):
    c = Client(); c.cookies['django_language'] = 'eo'
    body = c.get('/quote/E2E18N/').content.decode()
print('EVE name verbatim      :', 'Raven' in body)
print('rule name verbatim     :', 'Raven Special' in body)
print('system label translated:', 'Malpermesita' in body)
Snapshot.objects.filter(code='E2E18N').delete()
"
```
Expected: all three `True` — EVE data and the operator's rule name untouched, the system label translated.

- [ ] **Step 6: Verify existing snapshots survived the migration**

Run:
```bash
docker compose exec -T web python manage.py shell -c "
from buyback.models import SnapshotItem
for i in SnapshotItem.objects.all()[:10]:
    print(i.type_name, '|', i.price_source_kind, '|', repr(i.price_source_label), '|', i.flag_reason_code)
"
```
Expected: every row has a non-empty `price_source_kind`; no row shows a raw English string in a `_kind` or `_code` column.

- [ ] **Step 7: Commit any fixes**

```bash
git add -A
git commit -m "Fix issues found during frontend verification"
```

---

## Plan Self-Review

**Spec coverage:**

| Spec section | Covered by |
|---|---|
| §2 Translation boundary (4 buckets) | Tasks 4, 6 |
| §3 Domain emits keys | Task 2 |
| §3 SnapshotItem field split | Task 3 |
| §3 Data migration + reverse | Task 3 Steps 5–6 |
| §4 Django i18n foundation | Task 5 |
| §4 Language resolution order | Task 5 (LocaleMiddleware default) |
| §4 Admin stays English | Task 5 Step 4, verified Task 8 Step 4 |
| §4 HTMX switcher | Task 7 Step 1 |
| §4 English-only shipping | Task 5 Step 3 (`LANGUAGES`) |
| §5 Tailwind standalone build | Task 1 |
| §5 Dev watch sidecar | Task 1 Step 3 |
| §5 Pinned version | Task 1 Step 2 (`ARG TAILWIND_VERSION`) |
| §6 Semantic tokens | Task 1 Step 1 |
| §6 Verified accessible palette | Task 1 Step 1 |
| §6 Pre-paint theme script | Task 7 Step 1 |
| §6 Restyle scope | Tasks 7, 8 |
| §6 Unfold Nord tint | Task 8 Step 2 |
| §7 Updated existing assertions | Tasks 2 Step 7, 3 Step 9, 7 Step 7 |
| §7 Pseudo-locale pipeline test | Task 6 |
| §8 Migration risk (reverse migration) | Task 3 Step 5 |
| §8 Pinned Tailwind version | Task 1 Step 2 |

No spec requirement is unimplemented.

**Placeholder scan:** No TBD/TODO. Every code step contains complete code. The one conditional instruction (Task 3 Step 4, splitting the migration if Django removes columns eagerly) states both branches explicitly rather than deferring a decision.

**Type consistency:** `PriceDecision(percent, source_kind, rule_name, flagged, flag_reason)` is defined in Task 2 Step 3 and constructed in Step 4, consumed in Task 2 Step 6. `QuoteLine(..., price_source_kind, price_source_label, ..., flag_reason)` is defined in Task 2 Step 6 and consumed by `buyback/services.py` in Task 3 Step 7 and the filter in Task 4. `SnapshotItem.price_source_kind` / `.price_source_label` / `.flag_reason_code` are defined in Task 3 Step 3 and used identically in Tasks 4, 6, 7, and 9. `FlagReason` is defined once in `pricing/domain/decisions.py` and re-exported from `buyback/domain/quote.py` (Task 2 Step 5) so tests importing it from either location work.

**Known follow-ups, out of scope:**
- HTMX swapping `body` with `outerHTML` on language change re-runs the pre-paint script; the theme is re-read from `localStorage`, so it stays stable. Worth re-verifying if the swap target changes.
