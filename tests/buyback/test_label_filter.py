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
