# tests/buyback/test_migration_backfill.py
import importlib

# A module name starting with a digit cannot be imported with a plain
# `import` statement, so load it by name instead.
backfill = importlib.import_module(
    "buyback.migrations.0003_backfill_quoteitem_keys"
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
