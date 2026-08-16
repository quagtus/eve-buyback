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
