# EVE Buyback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an EVE Online buyback site where sellers paste an inventory list and receive a permanent, uniquely-linked price quote derived from the Janice appraisal API and admin-configured percentage rules.

**Architecture:** Four bounded-context Django apps (`catalog`, `pricing`, `buyback`, `siteconfig`). All branching business logic — price resolution, overlap validation, money rounding — lives in pure-Python `domain/` modules with zero Django imports, unit-tested without a database. Django models are thin persistence records; repositories map them into frozen domain objects. The Janice API sits behind a `PriceAppraisalGateway` port.

**Tech Stack:** Python 3.12, Django 5.1, PostgreSQL 16, HTMX, django-unfold, pytest + pytest-django, ijson, Docker Compose.

**Source spec:** `docs/superpowers/specs/2026-08-16-eve-buyback-design.md`

---

## Verified External Facts

These were confirmed against live sources while writing this plan. Do not re-derive them; do not assume differently.

**Janice API** (`https://janice.e-351.com/api/rest/v2/swagger.json`):
- `POST /api/rest/v2/appraisal`, auth header `X-ApiKey`, body is **raw plain text**, `Content-Type: text/plain`.
- Query params: `market` (int, 2=Jita), `pricing` (`buy|split|sell|purchase`), `pricingVariant` (`immediate|top5percent`), `persist` (bool, default true), `compactize` (bool, default true), `designation` (`appraisal|wtb|wts`), `pricePercentage` (double, default 1).
- Response top level: `code` (string, nullable), `created`, `expires`, `failures` (**string**, nullable — newline-separated, NOT an array), `items` (array).
- Response item: `amount` (quantity), `itemType.eid` (typeID), `itemType.name`, and `effectivePrices` / `immediatePrices` / `top5AveragePrices`, each containing `buyPrice`, `splitPrice`, `sellPrice`, `buyPriceTotal`, `splitPriceTotal`, `sellPriceTotal`.
- `effectivePrices` reflects the requested `pricingVariant`, so reading `effectivePrices.<basis>Price` honours both config settings.
- `expires` exists — **Janice appraisals expire.** Our snapshot page must never fetch from Janice at render time.
- `pricePercentage` must stay at `1`. It applies one flat percentage to the whole appraisal; our percentages are per-item. Setting it would silently double-discount every quote.

**EVERef reference data** (`https://data.everef.net/reference-data/reference-data-latest.tar.xz`, 14 MB):
- Archive contains `categories.json` (24 KB, 48 records), `groups.json` (1.3 MB, 1,610 records), `types.json` (**229 MB**, 52,865 records).
- All three are JSON **objects keyed by stringified ID**: `{"638": {...}}`.
- Category fields: `category_id`, `name` (language map — use `name["en"]`), `published`, `group_ids`.
- Group fields: `group_id`, `category_id`, `name` (language map), `published`, `type_ids`.
- Type fields: `type_id`, `name` (language map), `group_id`, `category_id`, `published`, plus ~40 more including multi-language `description` (this is what makes the file 229 MB).
- **`types.json` must be streamed, not `json.load`ed.** Verified: `ijson.kvitems` parses all 52,865 records in 2.4s at 19 MB peak RSS.
- **Filtering on `published` breaks referential integrity**: 46 published groups have unpublished categories, and 158 published types have unpublished groups. Verified fix: import **all** categories and **all** groups (tiny tables), and filter `published` only on types. That yields 26,992 types with zero FK violations.

**Real IDs for test fixtures** (these match the spec's worked-examples table exactly):

| Entity | ID |
|---|---|
| Category "Ship" | 6 |
| Category "Material" | 4 |
| Group "Battleship" | 27 |
| Group "Frigate" | 25 |
| Raven (Battleship) | 638 |
| Apocalypse (Battleship) | 642 |
| Rifter (Frigate) | 587 |
| Tristan (Frigate) | 593 |
| Tritanium (Material) | 34 |

---

## File Structure

```
eve-buyback/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── pytest.ini
├── manage.py
├── config/                          # Django project package (settings/urls/wsgi)
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── catalog/                         # EVE reference data. No business logic.
│   ├── models.py                    # EveCategory, EveGroup, EveType
│   ├── admin.py
│   └── management/commands/seed_catalog.py
├── pricing/                         # THE business logic lives here
│   ├── domain/
│   │   ├── decisions.py             # PriceDecision, PriceSourceKind, MatchLevel
│   │   ├── ruleset.py               # ItemClassification, Rule, RuleSet
│   │   ├── resolution.py            # resolve_price()
│   │   └── overlap.py               # find_overlap()
│   ├── models.py                    # CategoryDefaultPercent, CustomRule, SaleRule, BlacklistEntry
│   ├── repositories.py              # Django models -> frozen RuleSet
│   ├── admin.py
│   ├── views.py                     # rule summary page
│   └── templates/pricing/rule_summary.html
├── buyback/
│   ├── domain/
│   │   ├── money.py                 # Decimal rounding
│   │   ├── appraisal.py             # AppraisalItem, AppraisalResult
│   │   ├── gateway.py               # PriceAppraisalGateway protocol
│   │   └── quote.py                 # build_quote()
│   ├── infrastructure/janice.py     # JaniceAppraisalGateway
│   ├── models.py                    # Snapshot, SnapshotItem
│   ├── services.py                  # generate_snapshot() orchestration
│   ├── views.py
│   ├── admin.py
│   └── templates/buyback/{form,snapshot}.html
├── siteconfig/
│   ├── models.py                    # SiteConfig singleton
│   └── admin.py
└── tests/
    ├── pricing/{test_resolution.py,test_overlap.py,test_repositories.py}
    ├── buyback/{test_money.py,test_quote.py,test_janice.py,test_services.py,test_views.py}
    └── catalog/test_seed_catalog.py
```

**Percent convention, used everywhere:** `percent` is stored and passed as percentage points — `Decimal("80.00")` means 80%. Division by 100 happens only inside `buyback/domain/money.py`. Never store fractions.

---

## Task 1: Project scaffolding and Docker Compose

**Files:**
- Create: `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `pytest.ini`, `manage.py`, `config/__init__.py`, `config/settings.py`, `config/urls.py`, `config/wsgi.py`, `tests/__init__.py`, `tests/test_smoke.py`

- [ ] **Step 1: Create `requirements.txt`**

```
Django==5.1.4
psycopg[binary]==3.2.3
gunicorn==23.0.0
django-unfold==0.43.0
requests==2.32.3
ijson==3.3.0
django-ratelimit==4.1.0
whitenoise==6.8.2
pytest==8.3.4
pytest-django==4.9.0
responses==0.25.3
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10

  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy

volumes:
  pgdata:
```

- [ ] **Step 4: Create `.env.example`**

```
DJANGO_SECRET_KEY=change-me-in-production
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=buyback
POSTGRES_USER=buyback
POSTGRES_PASSWORD=buyback
DATABASE_URL=postgresql://buyback:buyback@db:5432/buyback

JANICE_API_KEY=your-janice-api-key
JANICE_BASE_URL=https://janice.e-351.com/api/rest/v2
```

- [ ] **Step 5: Create `manage.py`**

```python
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Create `config/settings.py`**

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "catalog",
    "pricing",
    "buyback",
    "siteconfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "buyback"),
        "USER": os.environ.get("POSTGRES_USER", "buyback"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "buyback"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Janice integration
JANICE_API_KEY = os.environ.get("JANICE_API_KEY", "")
JANICE_BASE_URL = os.environ.get("JANICE_BASE_URL", "https://janice.e-351.com/api/rest/v2")

# Public quote submission rate limit (see Task 17)
BUYBACK_RATE_LIMIT = os.environ.get("BUYBACK_RATE_LIMIT", "10/h")
```

- [ ] **Step 7: Create `config/urls.py` and `config/wsgi.py`**

```python
# config/urls.py
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
```

```python
# config/wsgi.py
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
```

- [ ] **Step 8: Create `pytest.ini`**

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings
python_files = test_*.py
testpaths = tests
```

- [ ] **Step 9: Create app package directories**

```bash
mkdir -p catalog/management/commands pricing/domain buyback/domain buyback/infrastructure siteconfig
mkdir -p tests/catalog tests/pricing tests/buyback
for d in catalog pricing pricing/domain buyback buyback/domain buyback/infrastructure siteconfig \
         catalog/management catalog/management/commands \
         tests tests/catalog tests/pricing tests/buyback; do touch $d/__init__.py; done
```

- [ ] **Step 10: Write the smoke test**

```python
# tests/test_smoke.py
def test_settings_import():
    from django.conf import settings

    assert "pricing" in settings.INSTALLED_APPS
    assert "buyback" in settings.INSTALLED_APPS
    assert "catalog" in settings.INSTALLED_APPS
    assert "siteconfig" in settings.INSTALLED_APPS
```

- [ ] **Step 11: Bring up the stack and run the test**

Run:
```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose exec web pytest tests/test_smoke.py -v
```
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add .
git commit -m "Scaffold Django project, Docker Compose, and test harness"
```

---

## Task 2: Catalog models

**Files:**
- Create: `catalog/models.py`, `catalog/admin.py`
- Test: `tests/catalog/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/catalog/test_models.py
import pytest

from catalog.models import EveCategory, EveGroup, EveType


@pytest.mark.django_db
def test_catalog_hierarchy_resolves_type_to_category():
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    raven = EveType.objects.create(id=638, name="Raven", group=battleship)

    assert raven.group.category.name == "Ship"
    assert str(raven) == "Raven"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/catalog/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError: cannot import name 'EveCategory'`.

- [ ] **Step 3: Write `catalog/models.py`**

Note: `id` is set explicitly to EVE's own IDs (not autoincrement), so records are stable across re-seeds.

```python
from django.db import models


class EveCategory(models.Model):
    """Top-level EVE item category, e.g. Ship. PK is EVE's category_id."""

    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255, db_index=True)

    class Meta:
        verbose_name_plural = "EVE categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class EveGroup(models.Model):
    """EVE item group, e.g. Battleship. PK is EVE's group_id."""

    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255, db_index=True)
    category = models.ForeignKey(
        EveCategory, on_delete=models.CASCADE, related_name="groups"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class EveType(models.Model):
    """Concrete EVE item type, e.g. Raven. PK is EVE's type_id."""

    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255, db_index=True)
    group = models.ForeignKey(
        EveGroup, on_delete=models.CASCADE, related_name="types"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
```

- [ ] **Step 4: Write `catalog/admin.py`**

The catalog is seeded reference data — read-only in the admin so nobody corrupts it by hand.

```python
from django.contrib import admin
from unfold.admin import ModelAdmin

from catalog.models import EveCategory, EveGroup, EveType


class ReadOnlyAdmin(ModelAdmin):
    search_fields = ["name"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EveCategory)
class EveCategoryAdmin(ReadOnlyAdmin):
    list_display = ["id", "name"]


@admin.register(EveGroup)
class EveGroupAdmin(ReadOnlyAdmin):
    list_display = ["id", "name", "category"]
    list_filter = ["category"]


@admin.register(EveType)
class EveTypeAdmin(ReadOnlyAdmin):
    list_display = ["id", "name", "group"]
    list_select_related = ["group", "group__category"]
```

- [ ] **Step 5: Make and run migrations, then run the test**

Run:
```bash
docker compose exec web python manage.py makemigrations catalog
docker compose exec web pytest tests/catalog/test_models.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add catalog tests/catalog
git commit -m "Add catalog models for EVE category/group/type hierarchy"
```

---

## Task 3: seed_catalog management command

Streams the 229 MB `types.json` rather than loading it. Imports **all** categories and groups but only published types — this is what keeps foreign keys intact (see Verified External Facts).

**Files:**
- Create: `catalog/management/commands/seed_catalog.py`
- Test: `tests/catalog/test_seed_catalog.py`

- [ ] **Step 1: Write the failing test**

The test drives the importer against a tiny fixture archive it builds itself, so it never touches the network.

```python
# tests/catalog/test_seed_catalog.py
import io
import json
import tarfile

import pytest

from catalog.management.commands.seed_catalog import import_reference_data
from catalog.models import EveCategory, EveGroup, EveType


def _lang(name):
    return {"en": name, "de": "ignored"}


def build_fixture_archive(path):
    categories = {
        "6": {"category_id": 6, "name": _lang("Ship"), "published": True},
        "4": {"category_id": 4, "name": _lang("Material"), "published": False},
    }
    groups = {
        "27": {"group_id": 27, "category_id": 6, "name": _lang("Battleship"), "published": True},
        "18": {"group_id": 18, "category_id": 4, "name": _lang("Mineral"), "published": False},
    }
    types = {
        "638": {"type_id": 638, "group_id": 27, "name": _lang("Raven"), "published": True},
        "34": {"type_id": 34, "group_id": 18, "name": _lang("Tritanium"), "published": True},
        "99": {"type_id": 99, "group_id": 27, "name": _lang("Unpublished"), "published": False},
    }
    with tarfile.open(path, "w:xz") as tar:
        for filename, payload in [
            ("categories.json", categories),
            ("groups.json", groups),
            ("types.json", types),
        ]:
            raw = json.dumps(payload).encode()
            info = tarfile.TarInfo(filename)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))


@pytest.mark.django_db
def test_import_loads_all_categories_and_groups_but_only_published_types(tmp_path):
    archive = tmp_path / "ref.tar.xz"
    build_fixture_archive(archive)

    result = import_reference_data(archive)

    # All categories and groups import, published or not, so FKs never dangle.
    assert EveCategory.objects.count() == 2
    assert EveGroup.objects.count() == 2

    # Only published types.
    assert EveType.objects.count() == 2
    assert not EveType.objects.filter(id=99).exists()

    # A published type under an unpublished group still imports cleanly.
    assert EveType.objects.get(id=34).group.category.name == "Material"

    assert EveType.objects.get(id=638).name == "Raven"
    assert result == {"categories": 2, "groups": 2, "types": 2}


@pytest.mark.django_db
def test_import_is_idempotent(tmp_path):
    archive = tmp_path / "ref.tar.xz"
    build_fixture_archive(archive)

    import_reference_data(archive)
    import_reference_data(archive)

    assert EveCategory.objects.count() == 2
    assert EveType.objects.count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/catalog/test_seed_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'catalog.management.commands.seed_catalog'`.

- [ ] **Step 3: Write `catalog/management/commands/seed_catalog.py`**

```python
"""Import EVE reference data from EVERef.

types.json is ~229 MB uncompressed, so it is streamed with ijson rather than
loaded into memory. Categories and groups are imported in full even when
unpublished: 46 published groups belong to unpublished categories and 158
published types belong to unpublished groups, so filtering the parent tables
would dangle foreign keys.
"""

import json
import tarfile
import tempfile
from pathlib import Path

import ijson
import requests
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import EveCategory, EveGroup, EveType

EVEREF_URL = "https://data.everef.net/reference-data/reference-data-latest.tar.xz"
BATCH_SIZE = 2000


def _english(name_field):
    """EVERef names are language maps: {"en": "Raven", "de": "..."}."""
    if not name_field:
        return ""
    return name_field.get("en") or ""


def download_archive(destination: Path, url: str = EVEREF_URL) -> Path:
    with requests.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        with open(destination, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                handle.write(chunk)
    return destination


@transaction.atomic
def import_reference_data(archive_path: Path) -> dict[str, int]:
    with tarfile.open(archive_path, "r:xz") as tar:
        categories = json.load(tar.extractfile("categories.json"))
        groups = json.load(tar.extractfile("groups.json"))

        EveCategory.objects.bulk_create(
            [
                EveCategory(id=int(key), name=_english(value["name"]))
                for key, value in categories.items()
            ],
            update_conflicts=True,
            update_fields=["name"],
            unique_fields=["id"],
        )

        EveGroup.objects.bulk_create(
            [
                EveGroup(
                    id=int(key),
                    name=_english(value["name"]),
                    category_id=value["category_id"],
                )
                for key, value in groups.items()
            ],
            update_conflicts=True,
            update_fields=["name", "category_id"],
            unique_fields=["id"],
        )

        known_group_ids = {int(key) for key in groups}
        type_count = 0
        batch = []

        # Re-open the member: extractfile handles are single-pass streams.
        with tarfile.open(archive_path, "r:xz") as type_tar:
            stream = type_tar.extractfile("types.json")
            for type_id, payload in ijson.kvitems(stream, ""):
                if not payload.get("published"):
                    continue
                group_id = payload.get("group_id")
                if group_id not in known_group_ids:
                    continue
                batch.append(
                    EveType(
                        id=int(type_id),
                        name=_english(payload.get("name")),
                        group_id=group_id,
                    )
                )
                if len(batch) >= BATCH_SIZE:
                    type_count += _flush(batch)
                    batch = []
            type_count += _flush(batch)

    return {
        "categories": len(categories),
        "groups": len(groups),
        "types": type_count,
    }


def _flush(batch: list[EveType]) -> int:
    if not batch:
        return 0
    EveType.objects.bulk_create(
        batch,
        update_conflicts=True,
        update_fields=["name", "group_id"],
        unique_fields=["id"],
    )
    return len(batch)


class Command(BaseCommand):
    help = "Import EVE category/group/type reference data from EVERef."

    def add_arguments(self, parser):
        parser.add_argument(
            "--archive",
            type=Path,
            default=None,
            help="Path to an already-downloaded reference-data tar.xz.",
        )

    def handle(self, *args, **options):
        archive = options["archive"]
        with tempfile.TemporaryDirectory() as tmpdir:
            if archive is None:
                archive = Path(tmpdir) / "reference-data.tar.xz"
                self.stdout.write(f"Downloading {EVEREF_URL} ...")
                download_archive(archive)
            self.stdout.write("Importing reference data ...")
            counts = import_reference_data(archive)
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {counts['categories']} categories, "
                f"{counts['groups']} groups, {counts['types']} types."
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/catalog/test_seed_catalog.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Run the real seed against live EVERef data**

Run:
```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_catalog
```
Expected output: `Imported 48 categories, 1610 groups, 26992 types.`
(Type count may drift slightly as CCP publishes new items; categories and groups should be very close to 48/1610.)

- [ ] **Step 6: Verify the known fixtures landed correctly**

Run:
```bash
docker compose exec web python manage.py shell -c "
from catalog.models import EveType
r = EveType.objects.get(id=638)
print(r.name, '|', r.group.name, '|', r.group.category.name)
"
```
Expected: `Raven | Battleship | Ship`

- [ ] **Step 7: Commit**

```bash
git add catalog tests/catalog
git commit -m "Add seed_catalog command streaming EVERef reference data"
```

---

## Task 4: Pricing domain value objects

Pure Python. No Django imports in `pricing/domain/`.

**Files:**
- Create: `pricing/domain/decisions.py`, `pricing/domain/ruleset.py`
- Test: `tests/pricing/test_ruleset.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pricing/test_ruleset.py
from datetime import datetime, timezone
from decimal import Decimal

from pricing.domain.decisions import MatchLevel
from pricing.domain.ruleset import ItemClassification, Rule

RAVEN = ItemClassification(type_id=638, group_id=27, category_id=6)


def make_rule(**kwargs):
    defaults = {
        "label": "test",
        "percent": Decimal("80.00"),
        "category_ids": frozenset(),
        "group_ids": frozenset(),
        "type_ids": frozenset(),
    }
    return Rule(**{**defaults, **kwargs})


def test_type_match_beats_group_and_category():
    rule = make_rule(
        category_ids=frozenset({6}),
        group_ids=frozenset({27}),
        type_ids=frozenset({638}),
    )
    assert rule.match_level(RAVEN) is MatchLevel.TYPE


def test_group_match_when_no_type_target():
    rule = make_rule(category_ids=frozenset({6}), group_ids=frozenset({27}))
    assert rule.match_level(RAVEN) is MatchLevel.GROUP


def test_category_match_when_only_category_targeted():
    rule = make_rule(category_ids=frozenset({6}))
    assert rule.match_level(RAVEN) is MatchLevel.CATEGORY


def test_no_match_returns_none():
    rule = make_rule(category_ids=frozenset({4}))
    assert rule.match_level(RAVEN) is None


def test_rule_without_window_is_always_active():
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    assert make_rule().is_active(now) is True


def test_rule_window_bounds_are_inclusive():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 31, tzinfo=timezone.utc)
    rule = make_rule(valid_from=start, valid_to=end)

    assert rule.is_active(start) is True
    assert rule.is_active(end) is True
    assert rule.is_active(datetime(2026, 7, 31, tzinfo=timezone.utc)) is False
    assert rule.is_active(datetime(2026, 9, 1, tzinfo=timezone.utc)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/pricing/test_ruleset.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing.domain.decisions'`.

- [ ] **Step 3: Write `pricing/domain/decisions.py`**

```python
"""Value objects describing a pricing decision. Pure Python — no Django."""

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum


class PriceSourceKind(StrEnum):
    BLACKLIST = "blacklist"
    SALE = "sale"
    CUSTOM = "custom"
    CATEGORY_DEFAULT = "category_default"
    NONE = "none"


class MatchLevel(IntEnum):
    """How specifically a rule matched an item. Higher wins within a tier."""

    CATEGORY = 1
    GROUP = 2
    TYPE = 3


@dataclass(frozen=True)
class PriceDecision:
    """The outcome of resolving one item against the rule set.

    `percent` is in percentage points: Decimal("80.00") means 80%.
    """

    percent: Decimal
    source_kind: PriceSourceKind
    source_label: str
    flagged: bool = False
    flag_reason: str | None = None
```

- [ ] **Step 4: Write `pricing/domain/ruleset.py`**

```python
"""Frozen, framework-free representation of the admin's configured rules."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from pricing.domain.decisions import MatchLevel


@dataclass(frozen=True)
class ItemClassification:
    """Where a single EVE item sits in the category hierarchy."""

    type_id: int
    group_id: int
    category_id: int


@dataclass(frozen=True)
class Rule:
    """A percentage rule targeting any mix of categories, groups and types.

    There is deliberately no `scope` field: specificity is derived from which
    target set matched, so there is no redundant state to keep in sync.
    A rule with no time window is always active.
    """

    label: str
    percent: Decimal
    category_ids: frozenset[int] = field(default_factory=frozenset)
    group_ids: frozenset[int] = field(default_factory=frozenset)
    type_ids: frozenset[int] = field(default_factory=frozenset)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def match_level(self, item: ItemClassification) -> MatchLevel | None:
        if item.type_id in self.type_ids:
            return MatchLevel.TYPE
        if item.group_id in self.group_ids:
            return MatchLevel.GROUP
        if item.category_id in self.category_ids:
            return MatchLevel.CATEGORY
        return None

    def is_active(self, now: datetime) -> bool:
        if self.valid_from is not None and now < self.valid_from:
            return False
        if self.valid_to is not None and now > self.valid_to:
            return False
        return True


@dataclass(frozen=True)
class RuleSet:
    """Everything price resolution needs, loaded once per quote."""

    blacklist_category_ids: frozenset[int] = field(default_factory=frozenset)
    blacklist_group_ids: frozenset[int] = field(default_factory=frozenset)
    blacklist_type_ids: frozenset[int] = field(default_factory=frozenset)
    sales: tuple[Rule, ...] = ()
    custom_rules: tuple[Rule, ...] = ()
    category_defaults: Mapping[int, Decimal] = field(default_factory=dict)

    def is_blacklisted(self, item: ItemClassification) -> bool:
        return (
            item.type_id in self.blacklist_type_ids
            or item.group_id in self.blacklist_group_ids
            or item.category_id in self.blacklist_category_ids
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/pricing/test_ruleset.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pricing tests/pricing
git commit -m "Add pure pricing value objects and rule matching"
```

---

## Task 5: Price resolution (the core logic)

This implements the spec's worked-examples table verbatim. Tiers are absolute; specificity only breaks ties *within* a tier.

**Files:**
- Create: `pricing/domain/resolution.py`
- Test: `tests/pricing/test_resolution.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pricing/test_resolution.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from pricing.domain.decisions import PriceSourceKind
from pricing.domain.resolution import resolve_price
from pricing.domain.ruleset import ItemClassification, Rule, RuleSet

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

RAVEN = ItemClassification(type_id=638, group_id=27, category_id=6)
APOCALYPSE = ItemClassification(type_id=642, group_id=27, category_id=6)
TRISTAN = ItemClassification(type_id=593, group_id=25, category_id=6)
RIFTER = ItemClassification(type_id=587, group_id=25, category_id=6)
TRITANIUM = ItemClassification(type_id=34, group_id=18, category_id=4)

BATTLESHIPS = Rule(
    label="Battleships",
    percent=Decimal("70.00"),
    group_ids=frozenset({27}),
)
RAVEN_SPECIAL = Rule(
    label="Raven Special",
    percent=Decimal("96.00"),
    type_ids=frozenset({638}),
)
SUMMER_SALE = Rule(
    label="Summer",
    percent=Decimal("90.00"),
    group_ids=frozenset({27}),
    valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
    valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
)
EXPIRED_SALE = Rule(
    label="Spring",
    percent=Decimal("95.00"),
    group_ids=frozenset({27}),
    valid_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
    valid_to=datetime(2026, 3, 31, tzinfo=timezone.utc),
)


def build_ruleset(*, sales=(), blacklist_type_ids=frozenset()):
    return RuleSet(
        blacklist_type_ids=blacklist_type_ids,
        sales=sales,
        custom_rules=(BATTLESHIPS, RAVEN_SPECIAL),
        category_defaults={6: Decimal("80.00")},
    )


def test_type_rule_wins_when_no_sale_active():
    decision = resolve_price(RAVEN, build_ruleset(sales=(EXPIRED_SALE,)), NOW)

    assert decision.percent == Decimal("96.00")
    assert decision.source_kind is PriceSourceKind.CUSTOM
    assert decision.source_label == "Raven Special"
    assert decision.flagged is False


def test_active_sale_beats_more_specific_custom_rule():
    """Tier beats specificity: a group-level sale outranks a type-level rule."""
    decision = resolve_price(RAVEN, build_ruleset(sales=(SUMMER_SALE,)), NOW)

    assert decision.percent == Decimal("90.00")
    assert decision.source_kind is PriceSourceKind.SALE


def test_group_rule_applies_when_no_type_rule():
    decision = resolve_price(APOCALYPSE, build_ruleset(), NOW)

    assert decision.percent == Decimal("70.00")
    assert decision.source_kind is PriceSourceKind.CUSTOM


def test_sale_applies_to_group_member_without_custom_type_rule():
    decision = resolve_price(APOCALYPSE, build_ruleset(sales=(SUMMER_SALE,)), NOW)

    assert decision.percent == Decimal("90.00")
    assert decision.source_kind is PriceSourceKind.SALE


def test_category_default_applies_when_no_rule_matches():
    decision = resolve_price(TRISTAN, build_ruleset(), NOW)

    assert decision.percent == Decimal("80.00")
    assert decision.source_kind is PriceSourceKind.CATEGORY_DEFAULT


def test_blacklist_beats_active_sale():
    ruleset = build_ruleset(
        sales=(SUMMER_SALE,), blacklist_type_ids=frozenset({587})
    )
    decision = resolve_price(RIFTER, ruleset, NOW)

    assert decision.percent == Decimal("0")
    assert decision.source_kind is PriceSourceKind.BLACKLIST
    assert decision.flagged is True
    assert decision.flag_reason == "Blacklisted"


def test_missing_category_default_is_flagged_not_an_error():
    decision = resolve_price(TRITANIUM, build_ruleset(), NOW)

    assert decision.percent == Decimal("0")
    assert decision.source_kind is PriceSourceKind.NONE
    assert decision.flagged is True
    assert decision.flag_reason == "No rule configured"


def test_most_specific_sale_wins_within_the_sale_tier():
    type_sale = Rule(
        label="Raven Weekend",
        percent=Decimal("99.00"),
        type_ids=frozenset({638}),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    decision = resolve_price(RAVEN, build_ruleset(sales=(SUMMER_SALE, type_sale)), NOW)

    assert decision.percent == Decimal("99.00")
    assert decision.source_label == "Raven Weekend"


@pytest.mark.parametrize(
    "item,expected",
    [
        (RAVEN, Decimal("96.00")),
        (APOCALYPSE, Decimal("70.00")),
        (TRISTAN, Decimal("80.00")),
    ],
)
def test_spec_table_without_sales(item, expected):
    assert resolve_price(item, build_ruleset(), NOW).percent == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/pricing/test_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing.domain.resolution'`.

- [ ] **Step 3: Write `pricing/domain/resolution.py`**

```python
"""Resolve one item to a buyback percentage.

Tiers are absolute and evaluated in order:
    1. Blacklist        (0%, flagged — beats everything, including sales)
    2. Active sale
    3. Custom rule
    4. Category default
    5. Nothing configured (0%, flagged)

Specificity (Type > Group > Category) only breaks ties *within* tier 2 and
tier 3. It never promotes a rule across tiers, which is what "a sale always
wins" means.
"""

from datetime import datetime
from decimal import Decimal

from pricing.domain.decisions import PriceDecision, PriceSourceKind
from pricing.domain.ruleset import ItemClassification, Rule, RuleSet

ZERO = Decimal("0")


def _best_match(rules: tuple[Rule, ...], item: ItemClassification) -> Rule | None:
    """Return the rule matching `item` at the most specific level, or None."""
    best: Rule | None = None
    best_level = None
    for rule in rules:
        level = rule.match_level(item)
        if level is None:
            continue
        if best_level is None or level > best_level:
            best, best_level = rule, level
    return best


def resolve_price(
    item: ItemClassification, ruleset: RuleSet, now: datetime
) -> PriceDecision:
    if ruleset.is_blacklisted(item):
        return PriceDecision(
            percent=ZERO,
            source_kind=PriceSourceKind.BLACKLIST,
            source_label="Blacklisted",
            flagged=True,
            flag_reason="Blacklisted",
        )

    active_sales = tuple(rule for rule in ruleset.sales if rule.is_active(now))
    sale = _best_match(active_sales, item)
    if sale is not None:
        return PriceDecision(
            percent=sale.percent,
            source_kind=PriceSourceKind.SALE,
            source_label=sale.label,
        )

    custom = _best_match(ruleset.custom_rules, item)
    if custom is not None:
        return PriceDecision(
            percent=custom.percent,
            source_kind=PriceSourceKind.CUSTOM,
            source_label=custom.label,
        )

    default = ruleset.category_defaults.get(item.category_id)
    if default is not None:
        return PriceDecision(
            percent=default,
            source_kind=PriceSourceKind.CATEGORY_DEFAULT,
            source_label="Category default",
        )

    return PriceDecision(
        percent=ZERO,
        source_kind=PriceSourceKind.NONE,
        source_label="No rule configured",
        flagged=True,
        flag_reason="No rule configured",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/pricing/test_resolution.py -v`
Expected: all tests PASS (11 including parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add pricing/domain/resolution.py tests/pricing/test_resolution.py
git commit -m "Implement price resolution with absolute tiers and specificity tiebreak"
```

---

## Task 6: Overlap validation

The spec forbids two rules of the same kind targeting the same entity at the same level. Sales additionally only conflict when their time windows overlap.

**Files:**
- Create: `pricing/domain/overlap.py`
- Test: `tests/pricing/test_overlap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pricing/test_overlap.py
from datetime import datetime, timezone
from decimal import Decimal

from pricing.domain.overlap import find_conflicts, windows_overlap
from pricing.domain.ruleset import Rule

AUG = datetime(2026, 8, 1, tzinfo=timezone.utc)
AUG_END = datetime(2026, 8, 31, tzinfo=timezone.utc)
SEP = datetime(2026, 9, 1, tzinfo=timezone.utc)
SEP_END = datetime(2026, 9, 30, tzinfo=timezone.utc)


def rule(label, percent="80.00", **targets):
    return Rule(label=label, percent=Decimal(percent), **targets)


def test_same_group_target_conflicts():
    a = rule("A", group_ids=frozenset({27}))
    b = rule("B", group_ids=frozenset({27}))

    assert find_conflicts(a, [b]) == ["B"]


def test_same_entity_at_different_levels_does_not_conflict():
    """Ship 80% + Battleship 70% must coexist; that is the whole point."""
    a = rule("Ships", category_ids=frozenset({6}))
    b = rule("Battleships", group_ids=frozenset({27}))

    assert find_conflicts(a, [b]) == []


def test_disjoint_targets_do_not_conflict():
    a = rule("A", type_ids=frozenset({638}))
    b = rule("B", type_ids=frozenset({642}))

    assert find_conflicts(a, [b]) == []


def test_partial_overlap_still_conflicts():
    a = rule("A", category_ids=frozenset({6, 4}))
    b = rule("B", category_ids=frozenset({4}))

    assert find_conflicts(a, [b]) == ["B"]


def test_sales_with_disjoint_windows_do_not_conflict():
    a = rule("Aug", group_ids=frozenset({27}), valid_from=AUG, valid_to=AUG_END)
    b = rule("Sep", group_ids=frozenset({27}), valid_from=SEP, valid_to=SEP_END)

    assert find_conflicts(a, [b]) == []


def test_sales_with_overlapping_windows_conflict():
    a = rule("Aug", group_ids=frozenset({27}), valid_from=AUG, valid_to=SEP)
    b = rule("Sep", group_ids=frozenset({27}), valid_from=AUG_END, valid_to=SEP_END)

    assert find_conflicts(a, [b]) == ["Sep"]


def test_open_ended_windows_overlap_everything():
    assert windows_overlap(None, None, AUG, AUG_END) is True
    assert windows_overlap(AUG, None, SEP, SEP_END) is True
    assert windows_overlap(None, AUG, SEP, SEP_END) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/pricing/test_overlap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing.domain.overlap'`.

- [ ] **Step 3: Write `pricing/domain/overlap.py`**

```python
"""Detect rules that would make price resolution ambiguous.

Two rules conflict when they target the same entity at the same level. Rules
targeting the same entity at *different* levels are fine and expected —
Ship 80% plus Battleship 70% is the intended way to express nested pricing.

Sales additionally only conflict when their validity windows intersect, so
sequential sales on the same target are legal.
"""

from datetime import datetime
from typing import Iterable

from pricing.domain.ruleset import Rule


def windows_overlap(
    a_from: datetime | None,
    a_to: datetime | None,
    b_from: datetime | None,
    b_to: datetime | None,
) -> bool:
    """Closed-interval intersection where None means unbounded."""
    if a_to is not None and b_from is not None and a_to < b_from:
        return False
    if b_to is not None and a_from is not None and b_to < a_from:
        return False
    return True


def _shares_target(a: Rule, b: Rule) -> bool:
    return bool(
        (a.category_ids & b.category_ids)
        or (a.group_ids & b.group_ids)
        or (a.type_ids & b.type_ids)
    )


def find_conflicts(candidate: Rule, existing: Iterable[Rule]) -> list[str]:
    """Return the labels of rules that conflict with `candidate`."""
    conflicts = []
    for other in existing:
        if not _shares_target(candidate, other):
            continue
        if not windows_overlap(
            candidate.valid_from, candidate.valid_to, other.valid_from, other.valid_to
        ):
            continue
        conflicts.append(other.label)
    return conflicts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/pricing/test_overlap.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pricing/domain/overlap.py tests/pricing/test_overlap.py
git commit -m "Add rule overlap detection for same-level conflicts"
```

---

## Task 7: Pricing Django models

**Files:**
- Create: `pricing/models.py`
- Test: `tests/pricing/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pricing/test_models.py
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from catalog.models import EveCategory, EveGroup, EveType
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule


@pytest.fixture
def ship_hierarchy(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    raven = EveType.objects.create(id=638, name="Raven", group=battleship)
    return ship, battleship, raven


@pytest.mark.django_db
def test_category_default_percent_is_unique_per_category(ship_hierarchy):
    ship, _, _ = ship_hierarchy
    CategoryDefaultPercent.objects.create(category=ship, percent=Decimal("80.00"))

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CategoryDefaultPercent.objects.create(category=ship, percent=Decimal("70.00"))


@pytest.mark.django_db
def test_custom_rule_targets_multiple_levels(ship_hierarchy):
    ship, battleship, raven = ship_hierarchy
    rule = CustomRule.objects.create(label="Mixed", percent=Decimal("75.00"))
    rule.categories.add(ship)
    rule.groups.add(battleship)
    rule.types.add(raven)

    assert rule.categories.count() == 1
    assert rule.types.first().name == "Raven"


@pytest.mark.django_db
def test_blacklist_entry_requires_exactly_one_target(ship_hierarchy):
    ship, battleship, _ = ship_hierarchy

    with pytest.raises(ValidationError):
        BlacklistEntry(category=ship, group=battleship).full_clean()

    with pytest.raises(ValidationError):
        BlacklistEntry().full_clean()

    entry = BlacklistEntry(category=ship)
    entry.full_clean()  # must not raise


@pytest.mark.django_db
def test_blacklist_exactly_one_target_enforced_by_database(ship_hierarchy):
    ship, battleship, _ = ship_hierarchy

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BlacklistEntry.objects.create(category=ship, group=battleship)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/pricing/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'BlacklistEntry'`.

- [ ] **Step 3: Write `pricing/models.py`**

```python
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from catalog.models import EveCategory, EveGroup, EveType

PERCENT_VALIDATORS = [
    MinValueValidator(Decimal("0")),
    MaxValueValidator(Decimal("1000")),
]


class CategoryDefaultPercent(models.Model):
    """Base buyback rate for an EVE category. 80.00 means 80%."""

    category = models.OneToOneField(
        EveCategory, on_delete=models.CASCADE, related_name="default_percent"
    )
    percent = models.DecimalField(
        max_digits=6, decimal_places=2, validators=PERCENT_VALIDATORS
    )

    class Meta:
        ordering = ["category__name"]

    def __str__(self):
        return f"{self.category.name}: {self.percent}%"


class TargetedRule(models.Model):
    """Shared shape for rules that target any mix of categories/groups/types."""

    label = models.CharField(max_length=120)
    percent = models.DecimalField(
        max_digits=6, decimal_places=2, validators=PERCENT_VALIDATORS
    )
    categories = models.ManyToManyField(EveCategory, blank=True)
    groups = models.ManyToManyField(EveGroup, blank=True)
    types = models.ManyToManyField(EveType, blank=True)

    class Meta:
        abstract = True
        ordering = ["label"]

    def __str__(self):
        return f"{self.label} ({self.percent}%)"


class CustomRule(TargetedRule):
    """Always-on percentage override. Beaten only by sales and the blacklist."""


class SaleRule(TargetedRule):
    """Time-boxed percentage that outranks custom rules while active."""

    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()

    class Meta(TargetedRule.Meta):
        abstract = False
        ordering = ["-valid_from"]

    def clean(self):
        super().clean()
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValidationError({"valid_to": "End must not precede start."})


class BlacklistEntry(models.Model):
    """One banned category, group, or type. Exactly one target must be set."""

    category = models.ForeignKey(
        EveCategory, null=True, blank=True, on_delete=models.CASCADE
    )
    group = models.ForeignKey(
        EveGroup, null=True, blank=True, on_delete=models.CASCADE
    )
    type = models.ForeignKey(
        EveType, null=True, blank=True, on_delete=models.CASCADE
    )

    class Meta:
        verbose_name_plural = "blacklist entries"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(category__isnull=False, group__isnull=True, type__isnull=True)
                    | models.Q(category__isnull=True, group__isnull=False, type__isnull=True)
                    | models.Q(category__isnull=True, group__isnull=True, type__isnull=False)
                ),
                name="blacklist_entry_exactly_one_target",
            )
        ]

    def clean(self):
        super().clean()
        targets = [self.category_id, self.group_id, self.type_id]
        if sum(target is not None for target in targets) != 1:
            raise ValidationError("Set exactly one of category, group, or type.")

    def __str__(self):
        target = self.category or self.group or self.type
        return f"Blacklisted: {target}"
```

Note: `CheckConstraint(condition=...)` is the Django 5.1 spelling. On Django < 5.1 the kwarg is `check=`.

- [ ] **Step 4: Make migrations and run tests**

Run:
```bash
docker compose exec web python manage.py makemigrations pricing
docker compose exec web pytest tests/pricing/test_models.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pricing tests/pricing
git commit -m "Add pricing models for defaults, custom rules, sales, and blacklist"
```

---

## Task 8: Pricing repository — models to frozen RuleSet

**Files:**
- Create: `pricing/repositories.py`
- Test: `tests/pricing/test_repositories.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pricing/test_repositories.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from catalog.models import EveCategory, EveGroup, EveType
from pricing.domain.decisions import PriceSourceKind
from pricing.domain.resolution import resolve_price
from pricing.domain.ruleset import ItemClassification
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule
from pricing.repositories import load_ruleset

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def hierarchy(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    frigate = EveGroup.objects.create(id=25, name="Frigate", category=ship)
    raven = EveType.objects.create(id=638, name="Raven", group=battleship)
    rifter = EveType.objects.create(id=587, name="Rifter", group=frigate)
    return {"ship": ship, "battleship": battleship, "raven": raven, "rifter": rifter}


@pytest.mark.django_db
def test_load_ruleset_round_trips_through_resolution(hierarchy):
    CategoryDefaultPercent.objects.create(
        category=hierarchy["ship"], percent=Decimal("80.00")
    )
    battleships = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    battleships.groups.add(hierarchy["battleship"])

    special = CustomRule.objects.create(label="Raven Special", percent=Decimal("96.00"))
    special.types.add(hierarchy["raven"])

    BlacklistEntry.objects.create(type=hierarchy["rifter"])

    ruleset = load_ruleset()

    raven = ItemClassification(type_id=638, group_id=27, category_id=6)
    assert resolve_price(raven, ruleset, NOW).percent == Decimal("96.00")

    rifter = ItemClassification(type_id=587, group_id=25, category_id=6)
    assert resolve_price(rifter, ruleset, NOW).source_kind is PriceSourceKind.BLACKLIST


@pytest.mark.django_db
def test_load_ruleset_includes_sales_with_windows(hierarchy):
    sale = SaleRule.objects.create(
        label="Summer",
        percent=Decimal("90.00"),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    sale.groups.add(hierarchy["battleship"])

    ruleset = load_ruleset()

    assert len(ruleset.sales) == 1
    assert ruleset.sales[0].label == "Summer"
    assert ruleset.sales[0].group_ids == frozenset({27})


@pytest.mark.django_db
def test_load_ruleset_on_empty_database_returns_empty_ruleset(db):
    ruleset = load_ruleset()

    assert ruleset.sales == ()
    assert ruleset.custom_rules == ()
    assert dict(ruleset.category_defaults) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/pricing/test_repositories.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing.repositories'`.

- [ ] **Step 3: Write `pricing/repositories.py`**

```python
"""Translate Django rule models into the frozen domain RuleSet.

Loaded once per quote so resolution never touches the ORM per item.
"""

from pricing.domain.ruleset import Rule, RuleSet
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule


def _to_rule(instance, *, with_window: bool) -> Rule:
    return Rule(
        label=instance.label,
        percent=instance.percent,
        category_ids=frozenset(c.id for c in instance.categories.all()),
        group_ids=frozenset(g.id for g in instance.groups.all()),
        type_ids=frozenset(t.id for t in instance.types.all()),
        valid_from=instance.valid_from if with_window else None,
        valid_to=instance.valid_to if with_window else None,
    )


def load_ruleset() -> RuleSet:
    entries = BlacklistEntry.objects.all()

    custom = CustomRule.objects.prefetch_related("categories", "groups", "types")
    sales = SaleRule.objects.prefetch_related("categories", "groups", "types")

    return RuleSet(
        blacklist_category_ids=frozenset(
            e.category_id for e in entries if e.category_id is not None
        ),
        blacklist_group_ids=frozenset(
            e.group_id for e in entries if e.group_id is not None
        ),
        blacklist_type_ids=frozenset(
            e.type_id for e in entries if e.type_id is not None
        ),
        sales=tuple(_to_rule(rule, with_window=True) for rule in sales),
        custom_rules=tuple(_to_rule(rule, with_window=False) for rule in custom),
        category_defaults={
            row.category_id: row.percent
            for row in CategoryDefaultPercent.objects.all()
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/pricing/test_repositories.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pricing/repositories.py tests/pricing/test_repositories.py
git commit -m "Add repository mapping pricing models to frozen RuleSet"
```

---

## Task 9: SiteConfig singleton

**Files:**
- Create: `siteconfig/models.py`
- Test: `tests/siteconfig/test_models.py` (create `tests/siteconfig/__init__.py` too)

- [ ] **Step 1: Write the failing test**

```python
# tests/siteconfig/test_models.py
import pytest

from siteconfig.models import PricingBasis, SiteConfig


@pytest.mark.django_db
def test_load_creates_a_single_row_with_defaults():
    config = SiteConfig.load()

    assert config.pk == 1
    assert config.market_id == 2  # Jita
    assert config.pricing_basis == PricingBasis.SPLIT
    assert SiteConfig.objects.count() == 1


@pytest.mark.django_db
def test_load_is_idempotent_and_saving_never_creates_a_second_row():
    first = SiteConfig.load()
    first.contract_to = "Buyback Corp"
    first.save()

    second = SiteConfig.load()

    assert SiteConfig.objects.count() == 1
    assert second.contract_to == "Buyback Corp"


@pytest.mark.django_db
def test_pk_is_forced_to_one_even_if_set_otherwise():
    config = SiteConfig(pk=99, contract_to="X")
    config.save()

    assert config.pk == 1
    assert SiteConfig.objects.count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/siteconfig/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siteconfig.models'`.

- [ ] **Step 3: Write `siteconfig/models.py`**

```python
from django.db import models


class PricingBasis(models.TextChoices):
    """Maps to Janice's `pricing` query parameter."""

    BUY = "buy", "Buy price"
    SPLIT = "split", "Split price"
    SELL = "sell", "Sell price"


class PricingVariant(models.TextChoices):
    """Maps to Janice's `pricingVariant` query parameter."""

    IMMEDIATE = "immediate", "Immediate"
    TOP5PERCENT = "top5percent", "Top 5 percent"


class SiteConfig(models.Model):
    """Admin-managed settings. Always exactly one row, pk=1.

    The Janice API key is deliberately NOT here — it is an environment
    variable, so the credential stays out of the database and its backups.
    """

    market_id = models.PositiveIntegerField(
        default=2, help_text="Janice market ID. 2 = Jita."
    )
    pricing_basis = models.CharField(
        max_length=16, choices=PricingBasis.choices, default=PricingBasis.SPLIT
    )
    pricing_variant = models.CharField(
        max_length=16,
        choices=PricingVariant.choices,
        default=PricingVariant.IMMEDIATE,
    )
    contract_to = models.CharField(
        max_length=255,
        blank=True,
        help_text="Character or corporation that sellers should contract to.",
    )
    contract_instructions = models.TextField(
        blank=True,
        help_text="Shown on every quote and frozen into each snapshot.",
    )

    class Meta:
        verbose_name = "site configuration"
        verbose_name_plural = "site configuration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """The singleton is never deleted."""
        return

    @classmethod
    def load(cls) -> "SiteConfig":
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def __str__(self):
        return "Site configuration"
```

- [ ] **Step 4: Create `tests/siteconfig/__init__.py`, migrate, run tests**

Run:
```bash
mkdir -p tests/siteconfig && touch tests/siteconfig/__init__.py
docker compose exec web python manage.py makemigrations siteconfig
docker compose exec web pytest tests/siteconfig/test_models.py -v
```
Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add siteconfig tests/siteconfig
git commit -m "Add SiteConfig singleton for market and pricing settings"
```

---

## Task 10: Money helpers

**Files:**
- Create: `buyback/domain/money.py`
- Test: `tests/buyback/test_money.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/buyback/test_money.py
from decimal import Decimal

from buyback.domain.money import line_total, sum_totals


def test_applies_percent_and_quantity():
    assert line_total(Decimal("100.00"), 3, Decimal("80.00")) == Decimal("240.00")


def test_rounds_half_up_to_two_places():
    # 1.005 * 1 * 100% -> 1.01, not 1.00 (banker's rounding would give 1.00)
    assert line_total(Decimal("1.005"), 1, Decimal("100.00")) == Decimal("1.01")


def test_zero_percent_yields_zero():
    assert line_total(Decimal("999999.99"), 100, Decimal("0")) == Decimal("0.00")


def test_result_always_has_two_decimal_places():
    assert str(line_total(Decimal("10"), 1, Decimal("50.00"))) == "5.00"


def test_total_is_the_sum_of_already_rounded_lines():
    """Displayed lines must add up to the displayed total, exactly."""
    lines = [
        line_total(Decimal("0.333"), 1, Decimal("100.00")),
        line_total(Decimal("0.333"), 1, Decimal("100.00")),
        line_total(Decimal("0.333"), 1, Decimal("100.00")),
    ]

    assert lines == [Decimal("0.33")] * 3
    assert sum_totals(lines) == Decimal("0.99")


def test_sum_of_nothing_is_zero():
    assert sum_totals([]) == Decimal("0.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_money.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'buyback.domain.money'`.

- [ ] **Step 3: Write `buyback/domain/money.py`**

```python
"""ISK arithmetic. Decimal only — never float.

`percent` is in percentage points (Decimal("80.00") == 80%). This is the only
module that divides by 100.

Lines are rounded before summing so the rendered line items always add up to
the rendered total.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

CENTS = Decimal("0.01")
HUNDRED = Decimal("100")


def quantize_isk(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def line_total(unit_price: Decimal, quantity: int, percent: Decimal) -> Decimal:
    return quantize_isk(unit_price * Decimal(quantity) * percent / HUNDRED)


def sum_totals(values: Iterable[Decimal]) -> Decimal:
    return quantize_isk(sum(values, Decimal("0")))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/buyback/test_money.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add buyback/domain/money.py tests/buyback/test_money.py
git commit -m "Add Decimal money helpers with half-up rounding"
```

---

## Task 11: Appraisal DTOs and gateway port

**Files:**
- Create: `buyback/domain/appraisal.py`, `buyback/domain/gateway.py`
- Test: `tests/buyback/test_appraisal.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/buyback/test_appraisal.py
from decimal import Decimal

from buyback.domain.appraisal import AppraisalItem, AppraisalResult


def test_result_reports_whether_it_has_priceable_items():
    empty = AppraisalResult(code="abc123", items=(), failures=("garbage line",))
    assert empty.has_items is False

    populated = AppraisalResult(
        code="abc123",
        items=(
            AppraisalItem(
                type_id=638, name="Raven", quantity=1, unit_price=Decimal("300000000")
            ),
        ),
        failures=(),
    )
    assert populated.has_items is True


def test_items_are_immutable():
    item = AppraisalItem(
        type_id=638, name="Raven", quantity=2, unit_price=Decimal("1.00")
    )
    try:
        item.quantity = 5
    except Exception as exc:
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("AppraisalItem must be frozen")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_appraisal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'buyback.domain.appraisal'`.

- [ ] **Step 3: Write `buyback/domain/appraisal.py`**

```python
"""Framework-free representation of an appraisal, independent of Janice."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AppraisalItem:
    type_id: int
    name: str
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class AppraisalResult:
    code: str
    items: tuple[AppraisalItem, ...]
    failures: tuple[str, ...]

    @property
    def has_items(self) -> bool:
        return bool(self.items)
```

- [ ] **Step 4: Write `buyback/domain/gateway.py`**

```python
"""Port for whatever prices items. Janice is one implementation."""

from typing import Protocol

from buyback.domain.appraisal import AppraisalResult


class AppraisalError(RuntimeError):
    """Raised when the upstream pricing service cannot be used."""


class PriceAppraisalGateway(Protocol):
    def create_appraisal(self, raw_text: str) -> AppraisalResult:
        """Price a raw pasted item list and persist it upstream.

        Raises AppraisalError on transport failure or an unusable response.
        """
        ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/buyback/test_appraisal.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add buyback/domain tests/buyback/test_appraisal.py
git commit -m "Add appraisal DTOs and PriceAppraisalGateway port"
```

---

## Task 12: Janice gateway adapter

**Files:**
- Create: `buyback/infrastructure/janice.py`
- Test: `tests/buyback/test_janice.py`

- [ ] **Step 1: Write the failing test**

Uses `responses` to stub HTTP. The JSON body mirrors the verified Janice schema.

```python
# tests/buyback/test_janice.py
from decimal import Decimal

import pytest
import responses

from buyback.domain.gateway import AppraisalError
from buyback.infrastructure.janice import JaniceAppraisalGateway

BASE_URL = "https://janice.test/api/rest/v2"
APPRAISAL_URL = f"{BASE_URL}/appraisal"

SAMPLE_RESPONSE = {
    "code": "4ovArs",
    "created": "2026-08-16T12:00:00Z",
    "expires": "2026-09-16T12:00:00Z",
    "failures": "not an item\nalso not an item",
    "items": [
        {
            "amount": 2,
            "itemType": {"eid": 638, "name": "Raven"},
            "effectivePrices": {
                "buyPrice": 250000000.0,
                "splitPrice": 275000000.0,
                "sellPrice": 300000000.0,
            },
        },
        {
            "amount": 1000,
            "itemType": {"eid": 34, "name": "Tritanium"},
            "effectivePrices": {
                "buyPrice": 4.5,
                "splitPrice": 5.0,
                "sellPrice": 5.5,
            },
        },
    ],
}


def build_gateway(basis="split"):
    return JaniceAppraisalGateway(
        api_key="test-key",
        base_url=BASE_URL,
        market_id=2,
        pricing_basis=basis,
        pricing_variant="immediate",
    )


@responses.activate
def test_parses_code_items_and_failures():
    responses.add(responses.POST, APPRAISAL_URL, json=SAMPLE_RESPONSE, status=200)

    result = build_gateway().create_appraisal("Raven 2")

    assert result.code == "4ovArs"
    assert len(result.items) == 2
    assert result.items[0].type_id == 638
    assert result.items[0].name == "Raven"
    assert result.items[0].quantity == 2
    assert result.items[0].unit_price == Decimal("275000000.0")
    assert result.failures == ("not an item", "also not an item")


@responses.activate
def test_pricing_basis_selects_the_matching_price_field():
    responses.add(responses.POST, APPRAISAL_URL, json=SAMPLE_RESPONSE, status=200)

    result = build_gateway(basis="sell").create_appraisal("Raven 2")

    assert result.items[0].unit_price == Decimal("300000000.0")


@responses.activate
def test_sends_required_headers_and_query_parameters():
    responses.add(responses.POST, APPRAISAL_URL, json=SAMPLE_RESPONSE, status=200)

    build_gateway().create_appraisal("Raven 2")

    request = responses.calls[0].request
    assert request.headers["X-ApiKey"] == "test-key"
    assert request.headers["Content-Type"] == "text/plain"
    assert request.body == b"Raven 2"

    from urllib.parse import parse_qs, urlparse

    params = parse_qs(urlparse(request.url).query)
    assert params["market"] == ["2"]
    assert params["persist"] == ["true"]
    assert params["compactize"] == ["true"]
    assert params["designation"] == ["wtb"]
    assert params["pricing"] == ["split"]
    assert params["pricingVariant"] == ["immediate"]
    # Must stay 1: Janice's own percentage would double-discount every quote.
    assert params["pricePercentage"] == ["1"]


@responses.activate
def test_null_failures_becomes_empty_tuple():
    payload = {**SAMPLE_RESPONSE, "failures": None}
    responses.add(responses.POST, APPRAISAL_URL, json=payload, status=200)

    assert build_gateway().create_appraisal("Raven 2").failures == ()


@responses.activate
def test_http_error_raises_appraisal_error():
    responses.add(responses.POST, APPRAISAL_URL, json={"error": "nope"}, status=500)

    with pytest.raises(AppraisalError):
        build_gateway().create_appraisal("Raven 2")


@responses.activate
def test_missing_code_raises_appraisal_error():
    payload = {**SAMPLE_RESPONSE, "code": None}
    responses.add(responses.POST, APPRAISAL_URL, json=payload, status=200)

    with pytest.raises(AppraisalError):
        build_gateway().create_appraisal("Raven 2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_janice.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'buyback.infrastructure.janice'`.

- [ ] **Step 3: Write `buyback/infrastructure/janice.py`**

```python
"""Janice implementation of PriceAppraisalGateway.

Schema verified against https://janice.e-351.com/api/rest/v2/swagger.json:
  request  : raw text body, Content-Type text/plain, X-ApiKey header
  response : {code, created, expires, failures (newline string|null), items[]}
  item     : {amount, itemType:{eid,name}, effectivePrices:{buyPrice,splitPrice,sellPrice}}

`effectivePrices` already reflects the requested pricingVariant, so reading
effectivePrices.<basis>Price honours both configured settings.
"""

from decimal import Decimal

import requests

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.domain.gateway import AppraisalError

PRICE_FIELDS = {
    "buy": "buyPrice",
    "split": "splitPrice",
    "sell": "sellPrice",
}

TIMEOUT_SECONDS = 30


class JaniceAppraisalGateway:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        market_id: int,
        pricing_basis: str,
        pricing_variant: str,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._market_id = market_id
        self._pricing_basis = pricing_basis
        self._pricing_variant = pricing_variant

    def create_appraisal(self, raw_text: str) -> AppraisalResult:
        try:
            response = requests.post(
                f"{self._base_url}/appraisal",
                params={
                    "market": self._market_id,
                    "designation": "wtb",
                    "pricing": self._pricing_basis,
                    "pricingVariant": self._pricing_variant,
                    "persist": "true",
                    "compactize": "true",
                    # Our percentages are per-item; Janice's flat one must stay 1.
                    "pricePercentage": 1,
                },
                headers={
                    "X-ApiKey": self._api_key,
                    "Content-Type": "text/plain",
                },
                data=raw_text.encode("utf-8"),
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise AppraisalError(f"Janice request failed: {exc}") from exc
        except ValueError as exc:
            raise AppraisalError("Janice returned a non-JSON response") from exc

        return self._to_result(payload)

    def _to_result(self, payload: dict) -> AppraisalResult:
        code = payload.get("code")
        if not code:
            raise AppraisalError("Janice response contained no appraisal code")

        price_field = PRICE_FIELDS[self._pricing_basis]
        items = []
        for entry in payload.get("items") or []:
            item_type = entry.get("itemType") or {}
            prices = entry.get("effectivePrices") or {}
            raw_price = prices.get(price_field)
            if item_type.get("eid") is None or raw_price is None:
                continue
            items.append(
                AppraisalItem(
                    type_id=int(item_type["eid"]),
                    name=item_type.get("name") or "",
                    quantity=int(entry.get("amount") or 0),
                    unit_price=Decimal(str(raw_price)),
                )
            )

        raw_failures = payload.get("failures") or ""
        failures = tuple(
            line.strip() for line in raw_failures.splitlines() if line.strip()
        )

        return AppraisalResult(code=code, items=tuple(items), failures=failures)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/buyback/test_janice.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Verify the mapping against the real API**

The stubbed schema came from the OpenAPI spec, not a live response. Confirm once with a real key before trusting it in production:

```bash
curl -s -X POST \
  "https://janice.e-351.com/api/rest/v2/appraisal?market=2&designation=wtb&pricing=split&pricingVariant=immediate&persist=true&compactize=true&pricePercentage=1" \
  -H "X-ApiKey: $JANICE_API_KEY" \
  -H "Content-Type: text/plain" \
  --data-binary $'Raven\t2\nTritanium\t1000\nnot-an-item\t1' \
  | python3 -m json.tool | head -60
```
Expected: a `code`, two entries in `items` with `itemType.eid` 638 and 34, and `not-an-item` appearing in `failures`. If any field name differs, fix `_to_result` and update the fixture in the test — the mapping is deliberately confined to that one method.

- [ ] **Step 6: Commit**

```bash
git add buyback/infrastructure tests/buyback/test_janice.py
git commit -m "Add Janice gateway adapter with verified schema mapping"
```

---

## Task 13: Quote assembly

Combines an appraisal with the rule set into priced lines. Pure function — no ORM, no HTTP.

**Files:**
- Create: `buyback/domain/quote.py`
- Test: `tests/buyback/test_quote.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/buyback/test_quote.py
from datetime import datetime, timezone
from decimal import Decimal

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.domain.quote import build_quote
from pricing.domain.ruleset import ItemClassification, Rule, RuleSet

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

CLASSIFICATIONS = {
    638: ItemClassification(type_id=638, group_id=27, category_id=6),
    587: ItemClassification(type_id=587, group_id=25, category_id=6),
    34: ItemClassification(type_id=34, group_id=18, category_id=4),
}

RULESET = RuleSet(
    blacklist_type_ids=frozenset({587}),
    custom_rules=(
        Rule(label="Battleships", percent=Decimal("70.00"), group_ids=frozenset({27})),
    ),
    category_defaults={6: Decimal("80.00")},
)


def appraisal(items, failures=()):
    return AppraisalResult(code="4ovArs", items=tuple(items), failures=tuple(failures))


def test_prices_a_normal_line():
    result = appraisal(
        [AppraisalItem(type_id=638, name="Raven", quantity=2, unit_price=Decimal("100.00"))]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    line = quote.lines[0]
    assert line.percent_applied == Decimal("70.00")
    assert line.line_total == Decimal("140.00")
    assert line.is_flagged is False
    assert quote.total_value == Decimal("140.00")


def test_blacklisted_line_is_flagged_and_contributes_nothing():
    result = appraisal(
        [
            AppraisalItem(type_id=638, name="Raven", quantity=1, unit_price=Decimal("100.00")),
            AppraisalItem(type_id=587, name="Rifter", quantity=5, unit_price=Decimal("50.00")),
        ]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    rifter = quote.lines[1]
    assert rifter.is_flagged is True
    assert rifter.flag_reason == "Blacklisted"
    assert rifter.line_total == Decimal("0.00")
    assert quote.total_value == Decimal("70.00")


def test_item_missing_from_catalog_is_flagged_not_crashed():
    result = appraisal(
        [AppraisalItem(type_id=99999, name="Mystery", quantity=1, unit_price=Decimal("10.00"))]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert quote.lines[0].is_flagged is True
    assert quote.lines[0].flag_reason == "Unrecognized item"
    assert quote.total_value == Decimal("0.00")


def test_category_without_default_is_flagged():
    result = appraisal(
        [AppraisalItem(type_id=34, name="Tritanium", quantity=100, unit_price=Decimal("5.00"))]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert quote.lines[0].is_flagged is True
    assert quote.lines[0].flag_reason == "No rule configured"


def test_janice_failures_become_flagged_zero_value_lines():
    result = appraisal(
        [AppraisalItem(type_id=638, name="Raven", quantity=1, unit_price=Decimal("100.00"))],
        failures=["definitely not an item"],
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert len(quote.lines) == 2
    failure_line = quote.lines[-1]
    assert failure_line.type_name == "definitely not an item"
    assert failure_line.type_id is None
    assert failure_line.is_flagged is True
    assert failure_line.flag_reason == "Could not be parsed"
    assert failure_line.line_total == Decimal("0.00")


def test_total_equals_the_sum_of_displayed_lines():
    result = appraisal(
        [
            AppraisalItem(type_id=638, name="Raven", quantity=1, unit_price=Decimal("0.333")),
            AppraisalItem(type_id=638, name="Raven", quantity=1, unit_price=Decimal("0.333")),
        ]
    )

    quote = build_quote(result, RULESET, CLASSIFICATIONS, NOW)

    assert quote.total_value == sum(line.line_total for line in quote.lines)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_quote.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'buyback.domain.quote'`.

- [ ] **Step 3: Write `buyback/domain/quote.py`**

```python
"""Turn an appraisal plus a rule set into priced, flagged quote lines.

Pure: no ORM, no HTTP, no clock. The caller supplies `now` and the type_id ->
ItemClassification mapping.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from buyback.domain.appraisal import AppraisalResult
from buyback.domain.money import line_total, sum_totals
from pricing.domain.decisions import PriceSourceKind
from pricing.domain.resolution import resolve_price
from pricing.domain.ruleset import ItemClassification, RuleSet

ZERO_ISK = Decimal("0.00")


@dataclass(frozen=True)
class QuoteLine:
    type_id: int | None
    type_name: str
    quantity: int
    unit_price: Decimal
    percent_applied: Decimal
    price_source: str
    line_total: Decimal
    is_flagged: bool
    flag_reason: str | None


@dataclass(frozen=True)
class Quote:
    code: str
    lines: tuple[QuoteLine, ...]
    total_value: Decimal


def build_quote(
    appraisal: AppraisalResult,
    ruleset: RuleSet,
    classifications: Mapping[int, ItemClassification],
    now: datetime,
) -> Quote:
    lines: list[QuoteLine] = []

    for item in appraisal.items:
        classification = classifications.get(item.type_id)
        if classification is None:
            lines.append(
                QuoteLine(
                    type_id=item.type_id,
                    type_name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    percent_applied=Decimal("0"),
                    price_source=PriceSourceKind.NONE.value,
                    line_total=ZERO_ISK,
                    is_flagged=True,
                    flag_reason="Unrecognized item",
                )
            )
            continue

        decision = resolve_price(classification, ruleset, now)
        total = (
            ZERO_ISK
            if decision.flagged
            else line_total(item.unit_price, item.quantity, decision.percent)
        )
        lines.append(
            QuoteLine(
                type_id=item.type_id,
                type_name=item.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                percent_applied=decision.percent,
                price_source=decision.source_label,
                line_total=total,
                is_flagged=decision.flagged,
                flag_reason=decision.flag_reason,
            )
        )

    for failure in appraisal.failures:
        lines.append(
            QuoteLine(
                type_id=None,
                type_name=failure,
                quantity=0,
                unit_price=ZERO_ISK,
                percent_applied=Decimal("0"),
                price_source=PriceSourceKind.NONE.value,
                line_total=ZERO_ISK,
                is_flagged=True,
                flag_reason="Could not be parsed",
            )
        )

    return Quote(
        code=appraisal.code,
        lines=tuple(lines),
        total_value=sum_totals(line.line_total for line in lines),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/buyback/test_quote.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add buyback/domain/quote.py tests/buyback/test_quote.py
git commit -m "Add pure quote assembly combining appraisal and pricing rules"
```

---

## Task 14: Snapshot models

**Files:**
- Create: `buyback/models.py`
- Test: `tests/buyback/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/buyback/test_models.py
from decimal import Decimal

import pytest

from buyback.models import Snapshot, SnapshotItem


@pytest.mark.django_db
def test_snapshot_is_keyed_by_the_janice_code():
    snapshot = Snapshot.objects.create(
        code="4ovArs",
        total_value=Decimal("140.00"),
        contract_to="Buyback Corp",
        contract_instructions="Contract to Buyback Corp in Jita.",
    )

    assert snapshot.pk == "4ovArs"
    assert Snapshot.objects.get(pk="4ovArs").total_value == Decimal("140.00")


@pytest.mark.django_db
def test_snapshot_items_preserve_resolved_values():
    snapshot = Snapshot.objects.create(code="4ovArs", total_value=Decimal("140.00"))
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=638,
        type_name="Raven",
        quantity=2,
        unit_price=Decimal("100.00"),
        percent_applied=Decimal("70.00"),
        price_source="Battleships",
        line_total=Decimal("140.00"),
    )

    item = snapshot.items.get()
    assert item.percent_applied == Decimal("70.00")
    assert item.price_source == "Battleships"
    assert item.is_flagged is False


@pytest.mark.django_db
def test_item_count_property():
    snapshot = Snapshot.objects.create(code="abc", total_value=Decimal("0.00"))
    for index in range(3):
        SnapshotItem.objects.create(
            snapshot=snapshot,
            type_id=index,
            type_name=f"Item {index}",
            quantity=1,
            unit_price=Decimal("1.00"),
            percent_applied=Decimal("100.00"),
            price_source="test",
            line_total=Decimal("1.00"),
        )

    assert snapshot.item_count == 3


@pytest.mark.django_db
def test_flagged_item_stores_its_reason():
    snapshot = Snapshot.objects.create(code="abc", total_value=Decimal("0.00"))
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=None,
        type_name="garbage line",
        quantity=0,
        unit_price=Decimal("0.00"),
        percent_applied=Decimal("0.00"),
        price_source="none",
        line_total=Decimal("0.00"),
        is_flagged=True,
        flag_reason="Could not be parsed",
    )

    assert snapshot.items.get().flag_reason == "Could not be parsed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'Snapshot'`.

- [ ] **Step 3: Write `buyback/models.py`**

```python
from django.db import models


class Snapshot(models.Model):
    """A permanent, frozen quote.

    The primary key IS the Janice appraisal code, so the same identifier
    resolves on this site and on janice.e-351.com/a/<code>. It is stored once,
    never duplicated into a second field.

    Every value here is resolved at generation time. Later edits to rules,
    blacklist entries, or site configuration must never alter an existing row.
    """

    code = models.CharField(primary_key=True, max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    total_value = models.DecimalField(max_digits=20, decimal_places=2)
    contract_to = models.CharField(max_length=255, blank=True)
    contract_instructions = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def item_count(self) -> int:
        return self.items.count()

    @property
    def janice_url(self) -> str:
        return f"https://janice.e-351.com/a/{self.code}"

    def __str__(self):
        return f"{self.code} ({self.total_value} ISK)"


class SnapshotItem(models.Model):
    """One frozen line of a snapshot.

    type_id is nullable because unparseable paste lines are preserved as
    flagged zero-value rows so the seller can see exactly what was rejected.
    """

    snapshot = models.ForeignKey(
        Snapshot, on_delete=models.CASCADE, related_name="items"
    )
    type_id = models.BigIntegerField(null=True, blank=True)
    type_name = models.CharField(max_length=255)
    quantity = models.BigIntegerField()
    unit_price = models.DecimalField(max_digits=20, decimal_places=2)
    percent_applied = models.DecimalField(max_digits=6, decimal_places=2)
    price_source = models.CharField(max_length=120)
    line_total = models.DecimalField(max_digits=20, decimal_places=2)
    is_flagged = models.BooleanField(default=False)
    flag_reason = models.CharField(max_length=120, null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.type_name} x{self.quantity}"
```

- [ ] **Step 4: Make migrations and run tests**

Run:
```bash
docker compose exec web python manage.py makemigrations buyback
docker compose exec web pytest tests/buyback/test_models.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add buyback tests/buyback/test_models.py
git commit -m "Add Snapshot and SnapshotItem models keyed by Janice code"
```

---

## Task 15: Snapshot generation service

**Files:**
- Create: `buyback/services.py`
- Test: `tests/buyback/test_services.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/buyback/test_services.py
from decimal import Decimal

import pytest

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.domain.gateway import AppraisalError
from buyback.models import Snapshot
from buyback.services import EmptyAppraisalError, generate_snapshot
from catalog.models import EveCategory, EveGroup, EveType
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule
from siteconfig.models import SiteConfig


class StubGateway:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.received_text = None

    def create_appraisal(self, raw_text):
        self.received_text = raw_text
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def configured(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    frigate = EveGroup.objects.create(id=25, name="Frigate", category=ship)
    EveType.objects.create(id=638, name="Raven", group=battleship)
    rifter = EveType.objects.create(id=587, name="Rifter", group=frigate)

    CategoryDefaultPercent.objects.create(category=ship, percent=Decimal("80.00"))
    rule = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    rule.groups.add(battleship)
    BlacklistEntry.objects.create(type=rifter)

    config = SiteConfig.load()
    config.contract_to = "Buyback Corp"
    config.contract_instructions = "Contract to Buyback Corp in Jita."
    config.save()
    return config


@pytest.mark.django_db
def test_generates_a_snapshot_with_frozen_values(configured):
    gateway = StubGateway(
        AppraisalResult(
            code="4ovArs",
            items=(
                AppraisalItem(
                    type_id=638, name="Raven", quantity=2, unit_price=Decimal("100.00")
                ),
            ),
            failures=(),
        )
    )

    snapshot = generate_snapshot("Raven\t2", gateway)

    assert snapshot.pk == "4ovArs"
    assert snapshot.total_value == Decimal("140.00")
    assert snapshot.contract_to == "Buyback Corp"
    assert gateway.received_text == "Raven\t2"

    item = snapshot.items.get()
    assert item.percent_applied == Decimal("70.00")
    assert item.price_source == "Battleships"


@pytest.mark.django_db
def test_later_rule_changes_do_not_alter_an_existing_snapshot(configured):
    gateway = StubGateway(
        AppraisalResult(
            code="4ovArs",
            items=(
                AppraisalItem(
                    type_id=638, name="Raven", quantity=1, unit_price=Decimal("100.00")
                ),
            ),
            failures=(),
        )
    )
    snapshot = generate_snapshot("Raven\t1", gateway)
    assert snapshot.total_value == Decimal("70.00")

    CustomRule.objects.filter(label="Battleships").update(percent=Decimal("10.00"))
    configured.contract_to = "Someone Else"
    configured.save()

    reloaded = Snapshot.objects.get(pk="4ovArs")
    assert reloaded.total_value == Decimal("70.00")
    assert reloaded.items.get().percent_applied == Decimal("70.00")
    assert reloaded.contract_to == "Buyback Corp"


@pytest.mark.django_db
def test_blacklisted_and_unparseable_lines_are_persisted_as_flagged(configured):
    gateway = StubGateway(
        AppraisalResult(
            code="abc999",
            items=(
                AppraisalItem(
                    type_id=587, name="Rifter", quantity=3, unit_price=Decimal("50.00")
                ),
            ),
            failures=("garbage",),
        )
    )

    snapshot = generate_snapshot("Rifter\t3\ngarbage", gateway)

    flagged = list(snapshot.items.all())
    assert len(flagged) == 2
    assert all(item.is_flagged for item in flagged)
    assert snapshot.total_value == Decimal("0.00")


@pytest.mark.django_db
def test_appraisal_with_no_items_raises_and_persists_nothing(configured):
    gateway = StubGateway(
        AppraisalResult(code="abc999", items=(), failures=("garbage",))
    )

    with pytest.raises(EmptyAppraisalError):
        generate_snapshot("garbage", gateway)

    assert Snapshot.objects.count() == 0


@pytest.mark.django_db
def test_gateway_failure_persists_nothing(configured):
    gateway = StubGateway(error=AppraisalError("boom"))

    with pytest.raises(AppraisalError):
        generate_snapshot("Raven\t1", gateway)

    assert Snapshot.objects.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_services.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'buyback.services'`.

- [ ] **Step 3: Write `buyback/services.py`**

```python
"""Application layer: orchestrates gateway, rules, and persistence."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from buyback.domain.gateway import PriceAppraisalGateway
from buyback.domain.quote import build_quote
from buyback.infrastructure.janice import JaniceAppraisalGateway
from buyback.models import Snapshot, SnapshotItem
from catalog.models import EveType
from pricing.domain.ruleset import ItemClassification
from pricing.repositories import load_ruleset
from siteconfig.models import SiteConfig


class EmptyAppraisalError(RuntimeError):
    """Nothing in the paste could be priced, so there is nothing to snapshot."""


def build_default_gateway() -> JaniceAppraisalGateway:
    config = SiteConfig.load()
    return JaniceAppraisalGateway(
        api_key=settings.JANICE_API_KEY,
        base_url=settings.JANICE_BASE_URL,
        market_id=config.market_id,
        pricing_basis=config.pricing_basis,
        pricing_variant=config.pricing_variant,
    )


def _classifications(type_ids) -> dict[int, ItemClassification]:
    rows = EveType.objects.filter(id__in=type_ids).values(
        "id", "group_id", "group__category_id"
    )
    return {
        row["id"]: ItemClassification(
            type_id=row["id"],
            group_id=row["group_id"],
            category_id=row["group__category_id"],
        )
        for row in rows
    }


@transaction.atomic
def generate_snapshot(
    raw_text: str, gateway: PriceAppraisalGateway | None = None
) -> Snapshot:
    gateway = gateway or build_default_gateway()

    appraisal = gateway.create_appraisal(raw_text)
    if not appraisal.has_items:
        raise EmptyAppraisalError("Janice could not price any item in that list.")

    ruleset = load_ruleset()
    classifications = _classifications({item.type_id for item in appraisal.items})
    quote = build_quote(appraisal, ruleset, classifications, timezone.now())

    config = SiteConfig.load()
    snapshot = Snapshot.objects.create(
        code=quote.code,
        total_value=quote.total_value,
        contract_to=config.contract_to,
        contract_instructions=config.contract_instructions,
    )
    SnapshotItem.objects.bulk_create(
        [
            SnapshotItem(
                snapshot=snapshot,
                type_id=line.type_id,
                type_name=line.type_name,
                quantity=line.quantity,
                unit_price=line.unit_price,
                percent_applied=line.percent_applied,
                price_source=line.price_source,
                line_total=line.line_total,
                is_flagged=line.is_flagged,
                flag_reason=line.flag_reason,
            )
            for line in quote.lines
        ]
    )
    return snapshot
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/buyback/test_services.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add buyback/services.py tests/buyback/test_services.py
git commit -m "Add snapshot generation service with frozen resolved values"
```

---

## Task 16: Public views and templates

**Files:**
- Create: `buyback/views.py`, `buyback/urls.py`, `templates/base.html`, `buyback/templates/buyback/form.html`, `buyback/templates/buyback/snapshot.html`, `buyback/templates/buyback/_error.html`
- Modify: `config/urls.py`
- Test: `tests/buyback/test_views.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/buyback/test_views.py
from decimal import Decimal

import pytest
from django.urls import reverse

from buyback.domain.appraisal import AppraisalItem, AppraisalResult
from buyback.models import Snapshot, SnapshotItem


@pytest.fixture
def priced_snapshot(db):
    snapshot = Snapshot.objects.create(
        code="4ovArs",
        total_value=Decimal("140.00"),
        contract_to="Buyback Corp",
        contract_instructions="Contract to Buyback Corp in Jita.",
    )
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=638,
        type_name="Raven",
        quantity=2,
        unit_price=Decimal("100.00"),
        percent_applied=Decimal("70.00"),
        price_source="Battleships",
        line_total=Decimal("140.00"),
    )
    SnapshotItem.objects.create(
        snapshot=snapshot,
        type_id=587,
        type_name="Rifter",
        quantity=1,
        unit_price=Decimal("50.00"),
        percent_applied=Decimal("0.00"),
        price_source="Blacklisted",
        line_total=Decimal("0.00"),
        is_flagged=True,
        flag_reason="Blacklisted",
    )
    return snapshot


@pytest.mark.django_db
def test_form_page_renders(client):
    response = client.get(reverse("buyback:form"))

    assert response.status_code == 200
    assert b"<form" in response.content


@pytest.mark.django_db
def test_snapshot_page_shows_items_totals_and_flags(client, priced_snapshot):
    response = client.get(reverse("buyback:snapshot", args=["4ovArs"]))

    assert response.status_code == 200
    body = response.content.decode()
    assert "Raven" in body
    assert "140.00" in body
    assert "Blacklisted" in body
    assert "Buyback Corp" in body
    assert "janice.e-351.com/a/4ovArs" in body


@pytest.mark.django_db
def test_unknown_snapshot_returns_404(client):
    assert client.get(reverse("buyback:snapshot", args=["nope"])).status_code == 404


@pytest.mark.django_db
def test_submitting_redirects_to_the_new_snapshot(client, monkeypatch, settings):
    settings.BUYBACK_RATE_LIMIT = "1000/h"

    class StubGateway:
        def create_appraisal(self, raw_text):
            return AppraisalResult(
                code="newcode",
                items=(
                    AppraisalItem(
                        type_id=638, name="Raven", quantity=1, unit_price=Decimal("10.00")
                    ),
                ),
                failures=(),
            )

    monkeypatch.setattr("buyback.views.build_default_gateway", lambda: StubGateway())

    response = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})

    assert response.status_code == 302
    assert response.url == reverse("buyback:snapshot", args=["newcode"])


@pytest.mark.django_db
def test_empty_paste_is_rejected_without_calling_the_gateway(client, settings):
    settings.BUYBACK_RATE_LIMIT = "1000/h"

    response = client.post(reverse("buyback:submit"), {"raw_text": "   "})

    assert response.status_code == 200
    assert b"Paste" in response.content
    assert Snapshot.objects.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/buyback/test_views.py -v`
Expected: FAIL with `django.urls.exceptions.NoReverseMatch`.

- [ ] **Step 3: Write `buyback/views.py`**

```python
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django_ratelimit.decorators import ratelimit

from buyback.domain.gateway import AppraisalError
from buyback.models import Snapshot
from buyback.services import (
    EmptyAppraisalError,
    build_default_gateway,
    generate_snapshot,
)
from siteconfig.models import SiteConfig


def form(request):
    return render(
        request, "buyback/form.html", {"config": SiteConfig.load()}
    )


def _error(request, message, status=200):
    return render(request, "buyback/_error.html", {"message": message}, status=status)


@ratelimit(key="ip", rate=lambda g, r: settings.BUYBACK_RATE_LIMIT, method="POST")
def submit(request):
    if request.method != "POST":
        return redirect("buyback:form")

    if getattr(request, "limited", False):
        return _error(
            request, "Too many quotes requested. Please try again later.", status=429
        )

    raw_text = (request.POST.get("raw_text") or "").strip()
    if not raw_text:
        return _error(request, "Paste your items before requesting a quote.")

    try:
        snapshot = generate_snapshot(raw_text, build_default_gateway())
    except EmptyAppraisalError:
        return _error(request, "None of those lines could be priced.")
    except AppraisalError:
        return _error(
            request, "The price service is unavailable right now. Please try again."
        )

    return redirect("buyback:snapshot", code=snapshot.pk)


def snapshot(request, code):
    instance = get_object_or_404(
        Snapshot.objects.prefetch_related("items"), pk=code
    )
    return render(request, "buyback/snapshot.html", {"snapshot": instance})
```

Note: `submit` returns a redirect, so HTMX is configured to follow it via `hx-boost` on the form (see the template). The `_error.html` partial is swapped in place on failure.

- [ ] **Step 4: Write `buyback/urls.py` and wire it into `config/urls.py`**

```python
# buyback/urls.py
from django.urls import path

from buyback import views

app_name = "buyback"

urlpatterns = [
    path("", views.form, name="form"),
    path("submit/", views.submit, name="submit"),
    path("quote/<str:code>/", views.snapshot, name="snapshot"),
]
```

```python
# config/urls.py
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("buyback.urls")),
]
```

- [ ] **Step 5: Write the templates**

```html
<!-- templates/base.html -->
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}EVE Buyback{% endblock %}</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <style>
      :root { color-scheme: dark; }
      body { font-family: system-ui, sans-serif; background: #14171c; color: #e6e6e6;
             max-width: 60rem; margin: 0 auto; padding: 2rem 1rem; line-height: 1.5; }
      textarea { width: 100%; min-height: 14rem; font-family: ui-monospace, monospace;
                 background: #1c2027; color: #e6e6e6; border: 1px solid #333a44;
                 border-radius: 6px; padding: .75rem; }
      table { width: 100%; border-collapse: collapse; margin-top: 1.5rem; }
      th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #262b33; }
      td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
      tr.flagged { background: #3a1d1d; }
      tr.flagged td { color: #ffb4b4; }
      .total { font-size: 1.4rem; font-weight: 700; margin-top: 1.5rem; }
      .error { background: #3a1d1d; color: #ffb4b4; padding: .75rem 1rem;
               border-radius: 6px; margin: 1rem 0; }
      button { background: #2f6feb; color: #fff; border: 0; border-radius: 6px;
               padding: .6rem 1.2rem; font-size: 1rem; cursor: pointer; margin-top: 1rem; }
      .muted { color: #9aa4b2; font-size: .9rem; }
    </style>
  </head>
  <body>
    <h1><a href="{% url 'buyback:form' %}" style="color:inherit;text-decoration:none">EVE Buyback</a></h1>
    {% block content %}{% endblock %}
  </body>
</html>
```

```html
<!-- buyback/templates/buyback/form.html -->
{% extends "base.html" %}
{% block content %}
  <p>Paste your items below (copy from your in-game inventory) to get a buyback quote.</p>

  <div id="result"></div>

  <form hx-post="{% url 'buyback:submit' %}" hx-target="#result" hx-swap="innerHTML">
    {% csrf_token %}
    <textarea name="raw_text" placeholder="Raven	1&#10;Tritanium	1000"></textarea>
    <button type="submit">Get quote</button>
  </form>

  {% if config.contract_to %}
    <p class="muted">Accepted contracts go to <strong>{{ config.contract_to }}</strong>.</p>
  {% endif %}
{% endblock %}
```

```html
<!-- buyback/templates/buyback/_error.html -->
<div class="error">{{ message }}</div>
```

```html
<!-- buyback/templates/buyback/snapshot.html -->
{% extends "base.html" %}
{% block title %}Quote {{ snapshot.code }}{% endblock %}
{% block content %}
  <h2>Quote {{ snapshot.code }}</h2>
  <p class="muted">
    Generated {{ snapshot.created_at }}. This page is permanent and will not change.
    Cross-check on <a href="{{ snapshot.janice_url }}">{{ snapshot.janice_url }}</a>.
  </p>

  <table>
    <thead>
      <tr>
        <th>Item</th>
        <th class="num">Qty</th>
        <th class="num">Unit price</th>
        <th class="num">Rate</th>
        <th>Source</th>
        <th class="num">Total</th>
      </tr>
    </thead>
    <tbody>
      {% for item in snapshot.items.all %}
        <tr class="{% if item.is_flagged %}flagged{% endif %}">
          <td>
            {{ item.type_name }}
            {% if item.is_flagged %}<br><small>{{ item.flag_reason }}</small>{% endif %}
          </td>
          <td class="num">{{ item.quantity }}</td>
          <td class="num">{{ item.unit_price }}</td>
          <td class="num">{{ item.percent_applied }}%</td>
          <td>{{ item.price_source }}</td>
          <td class="num">{{ item.line_total }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>

  <p class="total">Total offer: {{ snapshot.total_value }} ISK</p>

  {% if snapshot.contract_to %}
    <h3>How to sell</h3>
    <p>Create an in-game contract to <strong>{{ snapshot.contract_to }}</strong>.</p>
    {% if snapshot.contract_instructions %}
      <p>{{ snapshot.contract_instructions|linebreaksbr }}</p>
    {% endif %}
  {% endif %}
{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/buyback/test_views.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add buyback templates config/urls.py tests/buyback/test_views.py
git commit -m "Add public paste form and permanent snapshot page"
```

---

## Task 17: Rate limit coverage

The decorator was added in Task 16; this task proves it actually blocks.

**Files:**
- Test: `tests/buyback/test_rate_limit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/buyback/test_rate_limit.py
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse

from buyback.domain.appraisal import AppraisalItem, AppraisalResult


class StubGateway:
    def __init__(self):
        self.calls = 0

    def create_appraisal(self, raw_text):
        self.calls += 1
        return AppraisalResult(
            code=f"code{self.calls}",
            items=(
                AppraisalItem(
                    type_id=638, name="Raven", quantity=1, unit_price=Decimal("10.00")
                ),
            ),
            failures=(),
        )


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_submissions_beyond_the_limit_are_blocked(client, monkeypatch, settings):
    settings.BUYBACK_RATE_LIMIT = "2/h"
    gateway = StubGateway()
    monkeypatch.setattr("buyback.views.build_default_gateway", lambda: gateway)

    first = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})
    second = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})
    third = client.post(reverse("buyback:submit"), {"raw_text": "Raven\t1"})

    assert first.status_code == 302
    assert second.status_code == 302
    assert third.status_code == 429
    # The blocked request must never reach Janice.
    assert gateway.calls == 2
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `docker compose exec web pytest tests/buyback/test_rate_limit.py -v`
Expected: FAIL if `django_ratelimit` is not in `INSTALLED_APPS`/cache is unconfigured. If it passes immediately, the Task 16 decorator is already correct — continue to Step 3 anyway to pin the cache config.

- [ ] **Step 3: Add an explicit cache backend to `config/settings.py`**

`django_ratelimit` needs a real cache. The default local-memory cache is per-process, which is fine for a single Gunicorn worker but silently resets counters across workers — pin it explicitly so the behaviour is intentional and documented.

```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "buyback-ratelimit",
    }
}

# django-ratelimit
RATELIMIT_ENABLE = os.environ.get("RATELIMIT_ENABLE", "1") == "1"
```

- [ ] **Step 4: Run the test again**

Run: `docker compose exec web pytest tests/buyback/test_rate_limit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/buyback/test_rate_limit.py
git commit -m "Pin cache backend and cover public submit rate limiting"
```

---

## Task 18: Admin with django-unfold

**Files:**
- Create: `pricing/admin.py`, `buyback/admin.py`, `siteconfig/admin.py`
- Modify: `config/settings.py`
- Test: `tests/pricing/test_admin_validation.py`

- [ ] **Step 1: Write the failing test**

The admin form must reject a rule that overlaps an existing one at the same level.

```python
# tests/pricing/test_admin_validation.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from catalog.models import EveCategory, EveGroup
from pricing.admin import CustomRuleForm, SaleRuleForm
from pricing.models import CustomRule, SaleRule


@pytest.fixture
def hierarchy(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    frigate = EveGroup.objects.create(id=25, name="Frigate", category=ship)
    return ship, battleship, frigate


@pytest.mark.django_db
def test_rejects_a_custom_rule_overlapping_an_existing_one(hierarchy):
    _, battleship, _ = hierarchy
    existing = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    existing.groups.add(battleship)

    form = CustomRuleForm(
        data={"label": "Dupe", "percent": "60.00", "groups": [battleship.pk]}
    )

    assert form.is_valid() is False
    assert "Battleships" in str(form.errors)


@pytest.mark.django_db
def test_allows_a_rule_at_a_different_level(hierarchy):
    ship, battleship, _ = hierarchy
    existing = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    existing.groups.add(battleship)

    form = CustomRuleForm(
        data={"label": "Ships", "percent": "80.00", "categories": [ship.pk]}
    )

    assert form.is_valid() is True


@pytest.mark.django_db
def test_editing_a_rule_does_not_conflict_with_itself(hierarchy):
    _, battleship, _ = hierarchy
    existing = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    existing.groups.add(battleship)

    form = CustomRuleForm(
        instance=existing,
        data={"label": "Battleships", "percent": "75.00", "groups": [battleship.pk]},
    )

    assert form.is_valid() is True


@pytest.mark.django_db
def test_sales_with_disjoint_windows_are_allowed(hierarchy):
    _, battleship, _ = hierarchy
    august = SaleRule.objects.create(
        label="August",
        percent=Decimal("90.00"),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    august.groups.add(battleship)

    form = SaleRuleForm(
        data={
            "label": "September",
            "percent": "92.00",
            "groups": [battleship.pk],
            "valid_from": "2026-09-01 00:00:00",
            "valid_to": "2026-09-30 00:00:00",
        }
    )

    assert form.is_valid() is True


@pytest.mark.django_db
def test_sales_with_overlapping_windows_are_rejected(hierarchy):
    _, battleship, _ = hierarchy
    august = SaleRule.objects.create(
        label="August",
        percent=Decimal("90.00"),
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    august.groups.add(battleship)

    form = SaleRuleForm(
        data={
            "label": "Overlapping",
            "percent": "92.00",
            "groups": [battleship.pk],
            "valid_from": "2026-08-15 00:00:00",
            "valid_to": "2026-09-15 00:00:00",
        }
    )

    assert form.is_valid() is False
    assert "August" in str(form.errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/pricing/test_admin_validation.py -v`
Expected: FAIL with `ImportError: cannot import name 'CustomRuleForm'`.

- [ ] **Step 3: Write `pricing/admin.py`**

```python
from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin

from pricing.domain.overlap import find_conflicts
from pricing.domain.ruleset import Rule
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule


def _to_domain_rule(instance) -> Rule:
    return Rule(
        label=instance.label,
        percent=instance.percent,
        category_ids=frozenset(c.id for c in instance.categories.all()),
        group_ids=frozenset(g.id for g in instance.groups.all()),
        type_ids=frozenset(t.id for t in instance.types.all()),
        valid_from=getattr(instance, "valid_from", None),
        valid_to=getattr(instance, "valid_to", None),
    )


class TargetedRuleForm(forms.ModelForm):
    """Blocks rules that would make resolution ambiguous.

    Overlap is only a conflict at the same level: Ship 80% and Battleship 70%
    must coexist. Sales additionally only conflict when their windows intersect.
    """

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        candidate = Rule(
            label=cleaned.get("label") or "",
            percent=cleaned.get("percent") or 0,
            category_ids=frozenset(o.id for o in cleaned.get("categories", [])),
            group_ids=frozenset(o.id for o in cleaned.get("groups", [])),
            type_ids=frozenset(o.id for o in cleaned.get("types", [])),
            valid_from=cleaned.get("valid_from"),
            valid_to=cleaned.get("valid_to"),
        )

        others = self._meta.model.objects.prefetch_related(
            "categories", "groups", "types"
        )
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)

        conflicts = find_conflicts(candidate, [_to_domain_rule(o) for o in others])
        if conflicts:
            raise forms.ValidationError(
                "Overlaps existing rule(s) at the same level: "
                + ", ".join(conflicts)
                + ". Adjust the targets, or edit that rule instead."
            )
        return cleaned


class CustomRuleForm(TargetedRuleForm):
    class Meta:
        model = CustomRule
        fields = ["label", "percent", "categories", "groups", "types"]


class SaleRuleForm(TargetedRuleForm):
    class Meta:
        model = SaleRule
        fields = [
            "label",
            "percent",
            "categories",
            "groups",
            "types",
            "valid_from",
            "valid_to",
        ]


@admin.register(CategoryDefaultPercent)
class CategoryDefaultPercentAdmin(ModelAdmin):
    list_display = ["category", "percent"]
    list_select_related = ["category"]
    autocomplete_fields = ["category"]


@admin.register(CustomRule)
class CustomRuleAdmin(ModelAdmin):
    form = CustomRuleForm
    list_display = ["label", "percent"]
    search_fields = ["label"]
    autocomplete_fields = ["categories", "groups", "types"]


@admin.register(SaleRule)
class SaleRuleAdmin(ModelAdmin):
    form = SaleRuleForm
    list_display = ["label", "percent", "valid_from", "valid_to"]
    search_fields = ["label"]
    autocomplete_fields = ["categories", "groups", "types"]


@admin.register(BlacklistEntry)
class BlacklistEntryAdmin(ModelAdmin):
    list_display = ["__str__", "category", "group", "type"]
    autocomplete_fields = ["category", "group", "type"]
    list_select_related = ["category", "group", "type"]
```

- [ ] **Step 4: Write `buyback/admin.py` and `siteconfig/admin.py`**

```python
# buyback/admin.py
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from buyback.models import Snapshot, SnapshotItem


class SnapshotItemInline(TabularInline):
    model = SnapshotItem
    extra = 0
    can_delete = False
    fields = [
        "type_name", "quantity", "unit_price",
        "percent_applied", "price_source", "line_total", "flag_reason",
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Snapshot)
class SnapshotAdmin(ModelAdmin):
    """Quotes are immutable records — read-only bookkeeping only."""

    list_display = ["code", "created_at", "total_value", "item_count", "public_link"]
    search_fields = ["code"]
    date_hierarchy = "created_at"
    inlines = [SnapshotItemInline]
    readonly_fields = [
        "code", "created_at", "total_value", "contract_to", "contract_instructions",
    ]

    @admin.display(description="Public page")
    def public_link(self, obj):
        return format_html('<a href="/quote/{}/" target="_blank">open</a>', obj.code)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
```

```python
# siteconfig/admin.py
from django.contrib import admin
from unfold.admin import ModelAdmin

from siteconfig.models import SiteConfig


@admin.register(SiteConfig)
class SiteConfigAdmin(ModelAdmin):
    """Singleton — exactly one row, never added or deleted by hand."""

    list_display = ["__str__", "market_id", "pricing_basis", "contract_to"]

    def has_add_permission(self, request):
        return not SiteConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 5: Add the unfold config block to `config/settings.py`**

```python
UNFOLD = {
    "SITE_TITLE": "EVE Buyback Admin",
    "SITE_HEADER": "EVE Buyback",
    "SIDEBAR": {
        "show_search": True,
        "navigation": [
            {
                "title": "Pricing",
                "items": [
                    {"title": "Category defaults",
                     "link": "/admin/pricing/categorydefaultpercent/"},
                    {"title": "Custom rules", "link": "/admin/pricing/customrule/"},
                    {"title": "Sales", "link": "/admin/pricing/salerule/"},
                    {"title": "Blacklist", "link": "/admin/pricing/blacklistentry/"},
                    {"title": "Rule summary", "link": "/admin/pricing/summary/"},
                ],
            },
            {
                "title": "Buyback",
                "items": [
                    {"title": "Quotes", "link": "/admin/buyback/snapshot/"},
                    {"title": "Settings", "link": "/admin/siteconfig/siteconfig/"},
                ],
            },
        ],
    },
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/pricing/test_admin_validation.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 7: Create a superuser and eyeball the admin**

Run:
```bash
docker compose exec web python manage.py createsuperuser
```
Then open `http://localhost:8000/admin/` and confirm the Unfold theme renders and the sidebar groups appear.

- [ ] **Step 8: Commit**

```bash
git add pricing/admin.py buyback/admin.py siteconfig/admin.py config/settings.py tests/pricing/test_admin_validation.py
git commit -m "Add Unfold admin with overlap validation and read-only quote history"
```

---

## Task 19: Rule summary view

The one hand-built admin page: every rule in one place, grouped by match level, so overlapping intent is auditable at a glance.

**Files:**
- Create: `pricing/views.py`, `pricing/templates/pricing/rule_summary.html`
- Modify: `pricing/admin.py` (register the custom admin URL)
- Test: `tests/pricing/test_summary_view.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pricing/test_summary_view.py
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from catalog.models import EveCategory, EveGroup, EveType
from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule
from pricing.views import build_summary_rows

SUMMARY_URL = "/admin/pricing/summary/"


@pytest.fixture
def rules(db):
    ship = EveCategory.objects.create(id=6, name="Ship")
    battleship = EveGroup.objects.create(id=27, name="Battleship", category=ship)
    raven = EveType.objects.create(id=638, name="Raven", group=battleship)

    CategoryDefaultPercent.objects.create(category=ship, percent=Decimal("80.00"))

    group_rule = CustomRule.objects.create(label="Battleships", percent=Decimal("70.00"))
    group_rule.groups.add(battleship)

    type_rule = CustomRule.objects.create(label="Raven Special", percent=Decimal("96.00"))
    type_rule.types.add(raven)

    now = timezone.now()
    active = SaleRule.objects.create(
        label="Active Sale",
        percent=Decimal("90.00"),
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=1),
    )
    active.groups.add(battleship)

    expired = SaleRule.objects.create(
        label="Expired Sale",
        percent=Decimal("95.00"),
        valid_from=now - timedelta(days=30),
        valid_to=now - timedelta(days=10),
    )
    expired.groups.add(battleship)

    scheduled = SaleRule.objects.create(
        label="Future Sale",
        percent=Decimal("85.00"),
        valid_from=now + timedelta(days=10),
        valid_to=now + timedelta(days=20),
    )
    scheduled.groups.add(battleship)

    BlacklistEntry.objects.create(type=raven)
    return ship


@pytest.mark.django_db
def test_rows_are_ordered_most_specific_first(rules):
    rows = build_summary_rows(timezone.now())
    custom = [r for r in rows if r["kind"] == "Custom rule"]

    assert custom[0]["level"] == "Type"
    assert custom[-1]["level"] == "Group"


@pytest.mark.django_db
def test_sale_status_is_classified(rules):
    rows = build_summary_rows(timezone.now())
    statuses = {r["label"]: r["status"] for r in rows if r["kind"] == "Sale"}

    assert statuses["Active Sale"] == "active"
    assert statuses["Expired Sale"] == "expired"
    assert statuses["Future Sale"] == "scheduled"


@pytest.mark.django_db
def test_summary_includes_defaults_and_blacklist(rules):
    rows = build_summary_rows(timezone.now())
    kinds = {row["kind"] for row in rows}

    assert "Category default" in kinds
    assert "Blacklist" in kinds


@pytest.mark.django_db
def test_view_requires_staff_login(client, rules):
    anonymous = client.get(SUMMARY_URL)
    assert anonymous.status_code in (302, 403)

    User.objects.create_superuser("admin", "a@example.com", "password123")
    client.login(username="admin", password="password123")

    response = client.get(SUMMARY_URL)
    assert response.status_code == 200
    assert b"Raven Special" in response.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/pricing/test_summary_view.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing.views'`.

- [ ] **Step 3: Write `pricing/views.py`**

```python
"""Rule summary: every configured rule in one auditable list.

Django admin's per-model list views cannot show how rules interact, which is
exactly what matters when three rules touch the same item. This page sorts by
match level so the winning rule is obvious.
"""

from datetime import datetime

from django.shortcuts import render

from pricing.models import BlacklistEntry, CategoryDefaultPercent, CustomRule, SaleRule

LEVEL_ORDER = {"Type": 0, "Group": 1, "Category": 2}


def _targets(instance):
    """One row per match level the rule actually targets."""
    for level, manager in (
        ("Type", instance.types),
        ("Group", instance.groups),
        ("Category", instance.categories),
    ):
        names = [str(obj) for obj in manager.all()]
        if names:
            yield level, names


def _sale_status(sale, now: datetime) -> str:
    if now < sale.valid_from:
        return "scheduled"
    if now > sale.valid_to:
        return "expired"
    return "active"


def build_summary_rows(now: datetime) -> list[dict]:
    rows: list[dict] = []

    for sale in SaleRule.objects.prefetch_related("categories", "groups", "types"):
        for level, names in _targets(sale):
            rows.append({
                "kind": "Sale",
                "label": sale.label,
                "level": level,
                "targets": names,
                "percent": sale.percent,
                "status": _sale_status(sale, now),
                "window": f"{sale.valid_from:%Y-%m-%d} to {sale.valid_to:%Y-%m-%d}",
            })

    for rule in CustomRule.objects.prefetch_related("categories", "groups", "types"):
        for level, names in _targets(rule):
            rows.append({
                "kind": "Custom rule",
                "label": rule.label,
                "level": level,
                "targets": names,
                "percent": rule.percent,
                "status": "active",
                "window": "",
            })

    for default in CategoryDefaultPercent.objects.select_related("category"):
        rows.append({
            "kind": "Category default",
            "label": default.category.name,
            "level": "Category",
            "targets": [default.category.name],
            "percent": default.percent,
            "status": "active",
            "window": "",
        })

    for entry in BlacklistEntry.objects.select_related("category", "group", "type"):
        target = entry.category or entry.group or entry.type
        level = "Category" if entry.category_id else ("Group" if entry.group_id else "Type")
        rows.append({
            "kind": "Blacklist",
            "label": str(target),
            "level": level,
            "targets": [str(target)],
            "percent": None,
            "status": "active",
            "window": "",
        })

    kind_order = {"Blacklist": 0, "Sale": 1, "Custom rule": 2, "Category default": 3}
    rows.sort(key=lambda r: (kind_order[r["kind"]], LEVEL_ORDER[r["level"]], r["label"]))
    return rows


def rule_summary(request):
    from django.utils import timezone

    return render(
        request,
        "pricing/rule_summary.html",
        {
            "rows": build_summary_rows(timezone.now()),
            "title": "Rule summary",
        },
    )
```

- [ ] **Step 4: Register the URL in `pricing/admin.py`**

Append to `pricing/admin.py`:

```python
from django.urls import path

from pricing.views import rule_summary


class RuleSummaryProxy(CustomRule):
    """Proxy model used only to hang a custom admin URL off the pricing app."""

    class Meta:
        proxy = True
        verbose_name = "rule summary"
        verbose_name_plural = "rule summary"


@admin.register(RuleSummaryProxy)
class RuleSummaryAdmin(ModelAdmin):
    def get_urls(self):
        return [
            path(
                "",
                self.admin_site.admin_view(rule_summary),
                name="pricing_summary",
            ),
        ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

Then change the sidebar link in `config/settings.py` from `/admin/pricing/summary/` to `/admin/pricing/rulesummaryproxy/`, and update `SUMMARY_URL` in the test to match.

- [ ] **Step 5: Write `pricing/templates/pricing/rule_summary.html`**

```html
{% extends "admin/base_site.html" %}
{% block content %}
  <h1>Rule summary</h1>
  <p>Ordered by precedence: blacklist beats sales, sales beat custom rules,
     custom rules beat category defaults. Within a tier, the most specific
     match wins.</p>

  <table style="width:100%;border-collapse:collapse">
    <thead>
      <tr>
        <th style="text-align:left">Tier</th>
        <th style="text-align:left">Rule</th>
        <th style="text-align:left">Level</th>
        <th style="text-align:left">Targets</th>
        <th style="text-align:right">Percent</th>
        <th style="text-align:left">Status</th>
        <th style="text-align:left">Window</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
        <tr style="border-top:1px solid #ddd">
          <td>{{ row.kind }}</td>
          <td>{{ row.label }}</td>
          <td>{{ row.level }}</td>
          <td>{{ row.targets|join:", "|truncatechars:80 }}</td>
          <td style="text-align:right">
            {% if row.percent is not None %}{{ row.percent }}%{% else %}—{% endif %}
          </td>
          <td>{{ row.status }}</td>
          <td>{{ row.window }}</td>
        </tr>
      {% empty %}
        <tr><td colspan="7">No rules configured yet.</td></tr>
      {% endfor %}
    </tbody>
  </table>
{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/pricing/test_summary_view.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 7: Run the whole suite**

Run: `docker compose exec web pytest -v`
Expected: every test passes. Record the count.

- [ ] **Step 8: Commit**

```bash
git add pricing config/settings.py tests/pricing/test_summary_view.py
git commit -m "Add rule summary view showing precedence across all rule tiers"
```

---

## Task 20: End-to-end verification

No new code — this proves the assembled system does what the spec promised.

- [ ] **Step 1: Rebuild from scratch and seed**

```bash
docker compose down -v
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_catalog
docker compose exec web python manage.py createsuperuser
```
Expected: seed reports roughly `48 categories, 1610 groups, ~26992 types`.

- [ ] **Step 2: Configure rules in the admin**

At `http://localhost:8000/admin/`:
1. Site configuration → set `contract_to` and instructions, leave market 2 / split / immediate.
2. Category defaults → Ship = 80.
3. Custom rules → "Battleships", 70, group Battleship.
4. Custom rules → "Raven Special", 96, type Raven.
5. Blacklist → add type Rifter.
6. Open Rule summary and confirm all five appear with Type above Group.

- [ ] **Step 3: Confirm overlap validation blocks a duplicate**

Try to add another custom rule targeting group Battleship.
Expected: rejected with `Overlaps existing rule(s) at the same level: Battleships`.

- [ ] **Step 4: Generate a real quote**

Set a real `JANICE_API_KEY` in `.env`, `docker compose restart web`, then at `http://localhost:8000/` paste:

```
Raven	1
Rifter	2
Tritanium	1000
definitely-not-an-item	1
```

Expected on the resulting page:
- Redirected to `/quote/<code>/` with a Janice-style code.
- Raven priced at 96% (Raven Special).
- Rifter red-boxed, 0.00, reason "Blacklisted".
- Tritanium red-boxed with "No rule configured" (no Material default was set).
- `definitely-not-an-item` red-boxed with "Could not be parsed".
- Total equals the sum of the visible line totals.
- The Janice cross-link resolves to the same code.

- [ ] **Step 5: Prove the snapshot is frozen**

Change "Raven Special" to 10% in the admin, then reload the same `/quote/<code>/` URL.
Expected: the page is completely unchanged — same percent, same source label, same total.

- [ ] **Step 6: Confirm the quote appears in admin history**

Admin → Quotes. Expected: the snapshot listed with its code, total, item count, and a working public link. The record must be read-only.

- [ ] **Step 7: Commit any fixes**

```bash
git add -A
git commit -m "Fix issues found during end-to-end verification"
```

---

## Plan Self-Review

**Spec coverage:**

| Spec section | Covered by |
|---|---|
| §2 Tech stack | Task 1 |
| §3 Janice API contract | Tasks 11, 12 |
| §4 Four bounded-context apps | Tasks 2, 3, 4–8, 9, 10–16 |
| §4 Pure domain layering | Tasks 4, 5, 6, 10, 11, 13 |
| §4 Gateway port/adapter | Tasks 11, 12 |
| §5 catalog models | Task 2 |
| §5 pricing models + overlap validation | Tasks 6, 7, 18 |
| §5 Resolution tiers + specificity | Task 5 |
| §5 Worked-examples table | Task 5 tests |
| §5 Snapshot/SnapshotItem, code as PK | Task 14 |
| §5 Money handling (Decimal, half-up) | Task 10 |
| §6 One-step data flow | Tasks 15, 16 |
| §6 Empty appraisal → no snapshot | Task 15 |
| §7 Admin capabilities | Task 18 |
| §7 Rule summary view | Task 19 |
| §7 API key not in admin | Tasks 1, 9 |
| §8 Error handling, flagged items | Tasks 13, 15, 16 |
| §8 Rate limiting | Tasks 16, 17 |
| §9 Testing, Docker, seed_catalog | Tasks 1, 3, 20 |

No spec requirement is unimplemented.

**Type consistency check:** `PriceDecision(percent, source_kind, source_label, flagged, flag_reason)` is constructed in Task 5 and consumed in Task 13. `Rule(label, percent, category_ids, group_ids, type_ids, valid_from, valid_to)` is defined in Task 4 and constructed in Tasks 6, 8, 18. `RuleSet(blacklist_category_ids, blacklist_group_ids, blacklist_type_ids, sales, custom_rules, category_defaults)` is defined in Task 4 and built in Task 8. `AppraisalResult(code, items, failures)` is defined in Task 11, produced in Task 12, consumed in Tasks 13, 15. `resolve_price(item, ruleset, now)` and `line_total(unit_price, quantity, percent)` keep the same signatures at every call site. `Snapshot.code` is the PK everywhere; there is no second `janice_appraisal_code` field.

**Known follow-ups, deliberately out of scope:**
- `LocMemCache` makes rate-limit counters per-process. Fine for one Gunicorn worker; switch to Redis before scaling out.
- The Janice response mapping is stubbed from the OpenAPI spec. Task 12 Step 5 verifies it against the live API — do not skip it.
- `seed_catalog` is manual by design. If CCP ships new items, re-run it.
