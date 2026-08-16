# Drops the legacy price_source/flag_reason columns now that 0003 has
# backfilled every row into price_source_kind/price_source_label/
# flag_reason_code. Split out from 0002 so the backfill migration has the
# old columns available to read from.
#
# price_source is relaxed to nullable in migration STATE ONLY (no real DDL —
# database_operations is empty) before being dropped. This matters only for
# the reverse direction: RemoveField's backwards() re-adds a column using
# whatever field definition is in the state at this point. Without the
# relaxation, reversing this migration on a populated table would try to add
# back a NOT NULL column with no default and fail immediately, before 0003's
# backwards() ever gets a chance to repopulate it. Reusing a nullable
# definition lets the column come back empty, get repopulated by 0003's
# reverse RunPython, and never re-tightens to NOT NULL afterward — a
# permanently relaxed constraint on a legacy, about-to-be-dropped column is a
# fully acceptable cost for a reverse migration that must not crash on
# frozen snapshot data.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('buyback', '0003_backfill_snapshotitem_keys'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='snapshotitem',
                    name='price_source',
                    field=models.CharField(max_length=120, null=True, blank=True),
                ),
            ],
            database_operations=[],
        ),
        migrations.RemoveField(
            model_name='snapshotitem',
            name='flag_reason',
        ),
        migrations.RemoveField(
            model_name='snapshotitem',
            name='price_source',
        ),
    ]
