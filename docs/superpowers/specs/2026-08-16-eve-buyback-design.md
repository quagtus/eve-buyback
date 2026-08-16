# EVE Buyback Page — Design

## 1. Purpose

A web app for running an EVE Online item buyback program. Sellers paste an in-game inventory export, get an instant priced quote (via the Janice appraisal API, adjusted by admin-configured category percentages), and receive a permanent, unique link to that quote. The admin controls pricing rules, blacklists, and sales through an admin panel.

The defining constraint: **a generated quote is a permanent snapshot.** Once created, it never changes, even if the admin later edits percentages, blacklist entries, or contract instructions.

The developer (site owner) will personally maintain and extend this codebase long-term, so clean code, SOLID principles, and DDD-flavored structure are the top priority — not just a working prototype.

## 2. Tech Stack

- **Django** (Python), server-rendered templates + **HTMX** for interactivity (no SPA/JS framework)
- **PostgreSQL**
- **django-unfold** for a modern admin UI skin (keeps Django admin's built-in auth/permissions/CSRF, just re-styled)
- **Docker Compose** for local dev and deployment: `web` (Django + Gunicorn) and `db` (Postgres) services — no Celery/Redis, since the one external call (Janice) is fast enough to run synchronously inside the request that generates a quote

## 3. Architecture

Four Django apps, each a bounded context:

- **`catalog`** — EVE Categories/Groups/Types reference data. Plain data holder, no business logic. Seeded once from EVERef via a management command (`seed_catalog`), run manually after first `docker compose up` — not a recurring scheduled sync, since EVE's taxonomy rarely changes and can be re-run by hand when needed.
- **`pricing`** — category default percentages, custom rules, sale rules, blacklist entries, and the price resolution logic. This is where the real business logic lives.
- **`buyback`** — parses pasted item text, talks to Janice, applies `pricing` resolution, builds and persists the permanent snapshot, serves the public quote page.
- **`config`** — small admin-managed site settings: Janice API key, price basis (buy/sell/split), contract-to instructions text.

**Layering within `pricing` and `buyback`** (the two apps with real branching logic): domain logic — rule resolution, price calculation, paste parsing, snapshot assembly — is written as plain Python (dataclasses/functions, zero Django imports), fully unit-testable without a database or HTTP request. Django models are thin persistence records; a small repository/mapper translates between them and domain objects. `catalog` and `config` are simple data-holders and use Django models directly — no forced layering where there's no real logic to isolate.

**Dependency inversion at the one true external boundary:** the `buyback` domain depends on a `PriceAppraisalGateway` port (interface), with a `JaniceAppraisalGateway` adapter as the concrete implementation in infrastructure. If Janice's API changes, or a second price source is ever needed, only the adapter changes.

## 4. Domain Model

### `catalog`
- `EveCategory` (id, name) — e.g. Ship, Module, Drone
- `EveGroup` (id, name, category FK) — e.g. Battleship
- `EveType` (id, name, group FK) — e.g. Raven

### `pricing`
- `CategoryDefaultPercent` — one percent per `EveCategory` (the base rate, e.g. Ship = 80%)
- `CustomRule` — named rule with a scope (`CATEGORY`, `GROUP`, or `TYPE`), one or more target IDs at that scope, and a percent. Covers both bundling several EVE Categories under one custom-named rule and single Group/Type overrides (e.g. Battleship = 70%, Raven = 96%).
- `SaleRule` — same shape as `CustomRule`, plus `valid_from`/`valid_to` datetimes.
- `BlacklistEntry` — a scope (`CATEGORY`/`GROUP`/`TYPE`) + target IDs. No percent; forces 0.

One domain service owns the entire pricing decision:

```
resolve_price(type_id) -> PriceDecision { percent, source }
```

Priority order, highest to lowest:

1. **Blacklist** — hard stop, 0%, regardless of any active sale. Blacklist means "never buy this," and takes precedence even over a running sale on the same category.
2. **Sale rule**, if currently active (`now` within `[valid_from, valid_to]`)
3. **Custom rule**, most specific first: Type → Group → Category-bundle
4. **Category default** percent
5. No rule configured at all → treated like the "unpriceable" case (flagged, 0%) rather than erroring — surfaces as a visible gap on the snapshot instead of a crash.

### `buyback`
- `Snapshot` — id is the **Janice appraisal code itself**, reused directly as the public URL slug (`/quote/<janice-code>/`). Fields: `created_at`, `total_value`, `janice_appraisal_code`, and a **frozen copy** of the contract-to instructions text as it was at generation time.
- `SnapshotItem` — `type_id`, `type_name`, `quantity`, `unit_price` (from Janice), `percent_applied`, `price_source` (which rule won), `line_total`, `is_flagged`, `flag_reason`.

**Snapshots store resolved values, not live references.** Percent, price source, and contract instructions are copied in at generation time. Changing a category's percent or editing the blacklist later must never alter an already-generated page. Only `catalog` item names are looked up live (EVE item names don't change).

## 5. Data Flow (seller journey)

1. Seller lands on the public buyback page, pastes their EVE inventory export into a textarea, submits via HTMX POST.
2. `buyback` parses the text into `(type_name, quantity)` pairs, resolves each `type_name` against `catalog.EveType`. Unmatched names are flagged as unrecognized.
3. `buyback` calls `PriceAppraisalGateway.create_appraisal(items)` (the Janice adapter), using the admin-configured price basis (buy/sell/split). Janice returns per-item prices plus its own appraisal code.
4. For each priced item, `pricing.resolve_price(type_id)` returns the winning percent + source. Blacklisted or Janice-unpriceable items are flagged, price forced to 0, styled as a red box.
5. `buyback` builds and persists a `Snapshot` (id = Janice's appraisal code) with frozen `SnapshotItem`s, frozen contract instructions, and the computed total.
6. Seller is redirected to `/quote/<janice-code>/` — the permanent snapshot page.
7. That URL never re-renders live data; visiting it later always shows exactly what was generated.

## 6. Admin Capabilities

Built on Django admin, skinned with django-unfold:

- **Category defaults** — percent per `EveCategory`
- **Custom rules** — CRUD for Category-bundle/Group/Type-scoped rules with percentages. A dedicated **rule summary view** (the one hand-built piece, using HTMX to match the rest of the site) lists all active custom rules grouped/sorted by specificity, so overlapping rules are easy to audit at a glance.
- **Sales** — same as custom rules plus a time window; the summary view distinguishes active/scheduled/expired.
- **Blacklist** — mark Categories, Groups, or Types as blacklisted.
- **Quote history** — read-only list of every generated `Snapshot` (date, total value, item count, link) for bookkeeping.
- **Site config** — Janice API key, price basis, contract-to instructions text.

## 7. Error Handling & Edge Cases

- **Janice API failure/timeout** — inline error on the paste form; nothing persisted; seller can retry. No partial snapshots.
- **Empty/unparseable paste** — validation error before any API call.
- **Unrecognized item name** — flagged red, 0%, reason "unrecognized/not tradeable"; rest of the quote still generates.
- **Category with no default percent configured** — flagged like the unrecognized case rather than raising an error.
- **Duplicate item lines in the paste** — quantities summed per type before pricing.
- **Janice appraisal code collision** — practically impossible, but `Snapshot.id` uniqueness is still enforced at the DB level as a safety net.

## 8. Testing & Deployment

- Domain logic (`pricing.resolve_price`, paste parsing, snapshot assembly) is plain Python, unit tested without a database or network.
- The Janice gateway is tested against a stub implementation of the port interface; a real-API integration test exists but isn't part of the default fast test suite.
- Docker Compose: `web` (Django + Gunicorn) and `db` (Postgres); secrets (Janice API key, Django secret key, DB credentials) via `.env`; `seed_catalog` management command run manually after first bring-up.
