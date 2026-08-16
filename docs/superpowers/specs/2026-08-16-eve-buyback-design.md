# EVE Buyback Page — Design

## 1. Purpose

A web app for running an EVE Online item buyback program. Sellers paste an in-game inventory export, get an instant priced quote (via the Janice appraisal API, adjusted by admin-configured percentage rules), and land on a permanent, unique link to that quote. The admin controls pricing rules, blacklists, and sales through an admin panel.

The defining constraint: **a generated quote is a permanent snapshot.** Once created it never changes, even if the admin later edits percentages, blacklist entries, or contract instructions.

The developer (site owner) will personally maintain and extend this codebase long-term, so clean code, SOLID principles, and DDD-flavored structure are the top priority — not just a working prototype.

## 2. Tech Stack

- **Django** (Python), server-rendered templates + **HTMX** for interactivity (no SPA/JS framework)
- **PostgreSQL**
- **django-unfold** for a modern admin UI skin (keeps Django admin's built-in auth/permissions/CSRF, just re-styled)
- **Docker Compose**: `web` (Django + Gunicorn) and `db` (Postgres). No Celery/Redis — the one external call (Janice) runs synchronously inside the request that generates a quote.

## 3. The Janice API (verified)

Verified against `https://janice.e-351.com/api/rest/v2/swagger.json`. This section records what the integration actually depends on.

**`POST /api/rest/v2/appraisal`**
- Auth: `X-ApiKey` header
- Body: **raw plain text** — the pasted item list. Janice does the parsing.
- Query params used:
  - `market` (int, default `2` = Jita) — admin-configurable
  - `pricing` (`buy` | `split` | `sell` | `purchase`) — admin-configurable
  - `pricingVariant` (`immediate` | `top5percent`) — admin-configurable
  - `persist=true` — required; this is what mints the shareable code
  - `compactize=true` (default) — merges duplicate lines for us
  - `designation=wtb` — makes the Janice-side page read as a buy order, which matches a buyback
  - `pricePercentage` — **must stay at `1`** (see below)
- Response: `code` (the shareable ID, e.g. `4ovArs` → `janice.e-351.com/a/4ovArs`), `items[]` with `effectivePrices` (reflecting the chosen `pricing`/`pricingVariant`), and `failures` — a list of lines Janice could not parse.

**Two consequences that shape the design:**

1. **We do not write a paste parser.** The raw paste goes to Janice as the request body; parsed items and `failures` come back. EVE has many paste formats and Janice already handles them. `failures` is our "unrecognized item" signal.
2. **We do not use Janice's `pricePercentage`.** It applies one flat percentage across the whole appraisal. Our percentages are per-item and rule-derived, so this parameter stays at `1` and all percentage math happens on our side. Wiring it up would silently double-discount every quote.

`GET /api/rest/v2/appraisal/{code}` exists, but we never call it at render time — our page is built entirely from our own stored snapshot. If Janice ever prunes old appraisals, the cross-link may 404 while our page stays correct.

## 4. Architecture

Four Django apps, each a bounded context:

- **`catalog`** — EVE Categories/Groups/Types reference data. Plain data holder, no business logic. Seeded from EVERef via a `seed_catalog` management command, run once after first `docker compose up`. Its two jobs: backing the admin rule-picker UI, and mapping a Janice-returned typeID → group → category during rule resolution.
- **`pricing`** — category defaults, custom rules, sale rules, blacklist entries, and the resolution logic. This is where the real business logic lives.
- **`buyback`** — sends the paste to Janice, applies `pricing` resolution to the result, builds and persists the permanent snapshot, serves the public quote page.
- **`siteconfig`** — admin-managed settings (market, pricing basis, contract-to instructions). Named `siteconfig`, not `config`, to avoid colliding with the common Django `config/settings.py` project-package convention. Enforced as a singleton row.

**Layering within `pricing` and `buyback`** (the two apps with real branching logic): domain logic — rule resolution, price calculation, snapshot assembly — is plain Python (dataclasses/functions, zero Django imports), unit-testable without a database or HTTP request. Django models are thin persistence records; a small repository/mapper translates between them and domain objects. `catalog` and `siteconfig` are simple data-holders using Django models directly — no forced layering where there's no logic to isolate.

**Dependency inversion at the one external boundary:** the `buyback` domain depends on a `PriceAppraisalGateway` port, with `JaniceAppraisalGateway` as the concrete adapter. If Janice's API changes, or a second price source is ever needed, only the adapter changes.

## 5. Domain Model

### `catalog`
- `EveCategory` (id, name) — e.g. Ship, Module, Drone
- `EveGroup` (id, name, category FK) — e.g. Battleship
- `EveType` (id, name, group FK) — e.g. Raven

### `pricing`

- `CategoryDefaultPercent` — one percent per `EveCategory` (base rate, e.g. Ship = 80%)
- `CustomRule` — a **named** rule with a percent and three M2M target sets: `categories`, `groups`, `types`. A rule may populate any combination, which covers both "bundle several EVE categories under one name" and single Group/Type overrides. There is deliberately no `scope` enum field — match specificity is derived at resolution time from *which* set matched, so there is no redundant state to keep in sync.
- `SaleRule` — same shape as `CustomRule`, plus `valid_from`/`valid_to`.
- `BlacklistEntry` — one row per banned target: three nullable FKs (`category`/`group`/`type`) with a DB check constraint that **exactly one** is set. Modeled as individual rows rather than bundles because blacklisting is a flat, individually-managed list in the admin.

**Overlap validation.** Two rules of the same kind may not target the same entity at the same level:
- Two `CustomRule`s may not share a category, a group, or a type.
- Two `SaleRule`s may not share one **while their time windows also overlap** — sequential sales on the same target are legal.
- Cross-level overlap is *not* blocked; it's the whole point (Ship 80% + Battleship 70% + Raven 96% must coexist).
- Blacklist needs no overlap rule — banned is banned.

Validation lives in the domain layer and is surfaced through Django admin's `clean()`.

### Price resolution

One domain service owns the entire decision:

```
resolve_price(type_id, now) -> PriceDecision { percent, source, flagged, flag_reason }
```

**Tiers are absolute, highest first:**

1. **Blacklist** — 0%, flagged. Beats everything including an active sale. Blacklisted means never bought, full stop.
2. **Sale rule**, if `valid_from <= now <= valid_to`
3. **Custom rule**
4. **Category default percent**
5. **Nothing configured** — 0%, flagged, reason "no rule configured". Surfaces as a visible gap on the snapshot rather than a crash.

**Specificity (Type → Group → Category) breaks ties only *within* tier 2 and *within* tier 3.** It does not promote a rule across tiers: an active Battleship sale at 90% beats a Raven-specific custom rule at 96%, because sale is the higher tier. This is what "a sale always wins" means.

### Worked examples (also the acceptance criteria for tier 2–5 logic)

Config: Ship default 80% · CustomRule "Battleships" → group Battleship, 70% · CustomRule "Raven Special" → type Raven, 96% · SaleRule "Summer" → group Battleship, 90% · BlacklistEntry → type Rifter.

| Item | Sale active? | Result | Winning source |
|---|---|---|---|
| Raven | no | 96% | CustomRule (type) |
| Raven | yes | 90% | SaleRule — tier beats specificity |
| Apocalypse (Battleship) | no | 70% | CustomRule (group) |
| Apocalypse | yes | 90% | SaleRule (group) |
| Tristan (Frigate, no rule) | either | 80% | Ship category default |
| Rifter (blacklisted) | yes | 0%, flagged | Blacklist beats sale |
| Item in category with no default | either | 0%, flagged | No rule configured |
| Line Janice couldn't parse | either | 0%, flagged | Janice `failures` |

### `buyback`
- `Snapshot` — primary key **is** the Janice appraisal code (`CharField` PK), used directly as the public slug `/quote/<code>/`. Stored once, not duplicated into a second field. Other fields: `created_at`, `total_value`, and a **frozen copy** of the contract-to instructions text as it read at generation time.
- `SnapshotItem` — `type_id`, `type_name`, `quantity`, `unit_price` (Janice `effectivePrices`), `percent_applied`, `price_source` (which rule won), `line_total`, `is_flagged`, `flag_reason`.

**Snapshots store resolved values, not live references.** Percent, source, prices, and contract instructions are copied in at generation time. Later edits to rules, blacklist, or settings must never alter an already-generated page.

### Money handling

All monetary and percentage values are `Decimal`, never float. `line_total = round(unit_price * quantity * percent, 2)` using `ROUND_HALF_UP`; the grand total is the sum of the already-rounded line totals, so the displayed lines always add up to the displayed total. Flagged items contribute `0`.

## 6. Data Flow (seller journey)

One step — submitting the paste generates the permanent page directly.

1. Seller pastes their EVE inventory export into the public form and submits (HTMX POST).
2. `buyback` sends the raw text to `PriceAppraisalGateway.create_appraisal(...)` with `persist=true` and the admin-configured market/pricing/pricingVariant. Janice returns the `code`, priced `items[]`, and `failures`.
3. For each returned item, `pricing.resolve_price(type_id, now)` yields the percent and source. Blacklisted, unconfigured, and unpriceable items are flagged, forced to 0, and rendered in a red box. Entries in `failures` become flagged zero-value line items so the seller sees exactly what was rejected.
4. `buyback` persists a `Snapshot` keyed by the Janice code, with frozen `SnapshotItem`s, frozen contract instructions, and the computed total.
5. Seller is redirected to `/quote/<code>/` — permanent, never re-rendered from live data.

If Janice returns no parseable items at all, no snapshot is created and the form shows an error.

## 7. Admin Capabilities

Django admin skinned with django-unfold:

- **Category defaults** — percent per `EveCategory`
- **Custom rules** — CRUD over named rules with category/group/type targets and a percent
- **Sales** — same, plus a time window
- **Rule summary view** — the one hand-built page (HTMX). Lists all custom rules and sales together, grouped by match level and flagged active/scheduled/expired, so overlapping intent is auditable at a glance instead of inferred from a flat table.
- **Blacklist** — flat searchable list of banned categories/groups/types
- **Quote history** — read-only list of every `Snapshot` (date, total, item count, link)
- **Site config** — market, pricing, pricingVariant, contract-to instructions

The Janice API key is **not** here — it's an environment variable (§9).

## 8. Error Handling & Edge Cases

- **Janice API failure/timeout** — inline error on the form, nothing persisted, seller retries. No partial snapshots.
- **Empty paste** — validated before any API call.
- **Unparseable lines** — returned in `failures`; flagged at 0, rest of the quote still generates.
- **Category with no default percent** — flagged at 0 rather than raising.
- **Duplicate lines** — handled by Janice's `compactize=true`; no work on our side.
- **Rate limiting** — the submit endpoint is public and unauthenticated, and under one-step generation *every* submission consumes Janice API quota (the key is issued personally and tracked to prevent excessive traffic) and creates a permanent row on both sides. A per-IP rate limit on that endpoint is required, not optional.
- **Code collision** — Janice codes are unique; PK uniqueness enforces it anyway.

## 9. Testing & Deployment

- Domain logic (`resolve_price`, overlap validation, snapshot assembly, money rounding) is plain Python — unit tested with no database or network. The worked-examples table in §5 is the starting test suite.
- The Janice gateway is tested against a stub implementation of the port. A real-API integration test exists but is excluded from the default fast suite.
- Docker Compose: `web` (Django + Gunicorn) and `db` (Postgres). Secrets via `.env`: `JANICE_API_KEY`, `DJANGO_SECRET_KEY`, DB credentials.
- `seed_catalog` management command run once after first bring-up to import EVERef reference data.
