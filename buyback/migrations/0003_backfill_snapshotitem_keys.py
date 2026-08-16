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
