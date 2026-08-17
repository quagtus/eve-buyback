# EVE Buyback

A self-hosted buyback site for EVE Online. Players paste an inventory list,
get an instant priced quote, and receive a permanent link to it.

Prices come from the [Janice](https://janice.e-351.com) appraisal API, adjusted
by percentage rules you configure per item category, group or type.

## How it works

1. A seller pastes their items on the public page.
2. The raw text goes to Janice, which parses it and returns prices.
3. Each item is matched against your pricing rules and multiplied by the winning
   percentage.
4. The result is saved as a **permanent quote** at `/q/<code>/` and never
   changes, even if you later edit your rules.

The quote page shows the seller exactly what to type into EVE's contract dialog,
with copy buttons for each field.

## Pricing rules

Four tiers, evaluated in order. The first match wins:

| Tier | Beats everything below | Example |
|---|---|---|
| **Blacklist** | Item is never bought — 0%, flagged | Blacklist a specific ship |
| **Sale** | Time-boxed override | +5% on Battleships this weekend |
| **Custom rule** | Named, always on | `Raven Special` at 96% |
| **Category default** | Base rate per EVE category | Ships at 80% |

Within a tier, the most specific match wins: a rule targeting a Type beats one
targeting its Group, which beats one targeting its Category. Specificity never
promotes a rule *across* tiers — an active Battleship sale beats a Raven-specific
custom rule, because sale is the higher tier.

Overlapping rules at the same level are rejected when you save them, so the
outcome is always unambiguous. The admin has a **rule summary** page showing
every rule in one list, ordered by precedence.

## Checking contracts

Sellers put the quote code in the contract description. The admin page at
**Contracts → Contract check** reads your outstanding in-game contracts through
ESI and marks green the ones where the code, the price, and the contract's actual
contents all match the quote.

It is read-only — accepting a contract still happens in the game client. Setup is
four environment variables; see
[docs/design/contract-check.md](docs/design/contract-check.md).

## Requirements

- Docker and Docker Compose
- A Janice API key (request one from the Janice developer)

## Quick start

```bash
git clone <your-repo-url> eve-buyback
cd eve-buyback
cp .env.example .env          # then set JANICE_API_KEY

docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_catalog
docker compose exec web python manage.py createsuperuser
```

`seed_catalog` downloads EVE's item catalogue (~14 MB) from
[EVERef](https://everef.net) and imports around 27,000 item types. It is
idempotent — re-run it when CCP publishes new items.

The site is then at `http://localhost:8000`, the admin at `/admin/`.

Configure your buyback in **Site configuration**: which character or corporation
sellers should contract to, the station, and the market and pricing basis passed
to Janice.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for production.

## Stack

Django 5 with server-rendered templates and HTMX — no SPA. PostgreSQL,
Tailwind CSS v4 (standalone binary, no Node), and django-unfold for the admin.

Business logic lives in `pricing/domain/` and `buyback/domain/` as plain Python
with no Django imports, so it is unit-testable without a database. Django models
are thin persistence records, and the Janice integration sits behind a gateway
port so a second price source would only need a new adapter.

- [docs/design/architecture.md](docs/design/architecture.md) — domain model, pricing resolution, Janice integration
- [docs/design/frontend.md](docs/design/frontend.md) — design system, theming, internationalisation
- [docs/design/contract-check.md](docs/design/contract-check.md) — ESI contract verification
- [docs/design/reprocessing.md](docs/design/reprocessing.md) — reprocessed-value pricing for ore and ice

## Development

```bash
docker compose up -d                       # includes a Tailwind --watch sidecar
docker compose exec web pytest             # test suite
```

Domain tests need no database or network. The suite also checks things that are
easy to break silently: colour contrast, that suppressed focus outlines have a
replacement, and that the compiled stylesheet is actually reachable.

## Translations

The public site is translatable; the admin is intentionally English only.
English is the only locale shipped. To add one:

```bash
docker compose exec web python manage.py makemessages -l de
# fill in locale/de/LC_MESSAGES/django.po
docker compose exec web python manage.py compilemessages
```

Then add it to `LANGUAGES` in `config/settings.py`. The language switcher appears
automatically once more than one locale is configured.

EVE item names and your own rule names are never translated — only the site's
own text is.

## Licence

MIT — see [LICENSE](LICENSE).

Not affiliated with CCP Games. EVE Online and all related trademarks are the
property of CCP hf.
