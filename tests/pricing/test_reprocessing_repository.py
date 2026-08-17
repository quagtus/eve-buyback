"""Loading reprocessing rules out of the database into the frozen RuleSet."""

from decimal import Decimal

import pytest

from catalog.models import EveCategory, EveGroup, EveType
from pricing.models import ReprocessingRule
from pricing.repositories import load_ruleset


@pytest.fixture
def targets(db):
    asteroid = EveCategory.objects.create(id=25, name="Asteroid")
    ice = EveGroup.objects.create(id=465, name="Ice", category=asteroid)
    veldspar_group = EveGroup.objects.create(id=462, name="Veldspar", category=asteroid)
    icicle = EveType.objects.create(id=16262, name="Clear Icicle", group=ice)
    EveType.objects.create(id=1230, name="Veldspar", group=veldspar_group)
    return asteroid, ice, icicle


@pytest.mark.django_db
def test_a_ruleset_with_no_reprocessing_rules_is_empty(db):
    assert load_ruleset().reprocessing_rules == ()


@pytest.mark.django_db
def test_reprocessing_rules_load_with_their_targets_and_yield(targets):
    asteroid, ice, _ = targets
    ore_rule = ReprocessingRule.objects.create(
        label="Ore", yield_rate=Decimal("0.8734")
    )
    ore_rule.categories.add(asteroid)
    ice_rule = ReprocessingRule.objects.create(
        label="Ice", yield_rate=Decimal("0.9063")
    )
    ice_rule.groups.add(ice)

    loaded = {rule.label: rule for rule in load_ruleset().reprocessing_rules}

    assert loaded["Ore"].yield_rate == Decimal("0.8734")
    assert loaded["Ore"].category_ids == frozenset({25})
    assert loaded["Ice"].group_ids == frozenset({465})
    assert loaded["Ice"].type_ids == frozenset()


@pytest.mark.django_db
def test_a_type_targeted_rule_loads(targets):
    _, _, icicle = targets
    rule = ReprocessingRule.objects.create(label="Icicle", yield_rate=Decimal("0.95"))
    rule.types.add(icicle)

    loaded = load_ruleset().reprocessing_rules[0]

    assert loaded.type_ids == frozenset({16262})


@pytest.mark.django_db
def test_the_yield_rate_keeps_four_decimal_places(targets):
    asteroid, _, _ = targets
    rule = ReprocessingRule.objects.create(label="Ore", yield_rate=Decimal("0.9063"))
    rule.categories.add(asteroid)

    assert load_ruleset().reprocessing_rules[0].yield_rate == Decimal("0.9063")


@pytest.mark.django_db
def test_percentage_rules_are_unaffected(targets):
    """percent moved from the abstract base into the concrete classes; the
    existing loaders must be untouched by that."""
    from pricing.models import CustomRule

    asteroid, _, _ = targets
    rule = CustomRule.objects.create(label="Ore pct", percent=Decimal("80.00"))
    rule.categories.add(asteroid)

    assert load_ruleset().custom_rules[0].percent == Decimal("80.00")
