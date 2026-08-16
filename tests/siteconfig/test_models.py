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


@pytest.mark.django_db
def test_queryset_bulk_delete_does_not_remove_the_singleton():
    SiteConfig.load()

    SiteConfig.objects.all().delete()

    assert SiteConfig.objects.count() == 1
