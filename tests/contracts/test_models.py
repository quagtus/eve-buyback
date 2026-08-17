"""One linked character, replaced on re-login.

The singleton is deliberate: the operator checks their own contracts, and
checking a different character's means logging in as that character.
"""

import pytest
from django.db import IntegrityError, transaction

from contracts.models import EsiCharacter


@pytest.mark.django_db
def test_current_is_none_before_anything_is_linked():
    assert EsiCharacter.current() is None


@pytest.mark.django_db
def test_relinking_replaces_the_row_rather_than_adding_one():
    """The path link_character() takes: load the existing row, overwrite it."""
    EsiCharacter.objects.create(
        character_id=1, character_name="First", refresh_token_ciphertext="a"
    )

    character = EsiCharacter.current()
    character.character_id = 2
    character.character_name = "Second"
    character.refresh_token_ciphertext = "b"
    character.save()

    assert EsiCharacter.objects.count() == 1
    assert EsiCharacter.current().character_name == "Second"


@pytest.mark.django_db
def test_a_second_row_cannot_be_created():
    """save() pins pk=1, so a stray create() collides instead of quietly adding
    a second character. Same behaviour as SiteConfig."""
    EsiCharacter.objects.create(
        character_id=1, character_name="First", refresh_token_ciphertext="a"
    )

    # Wrapped in a savepoint so the failed insert does not poison the outer
    # test transaction and make the assertion below unrunnable.
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            EsiCharacter.objects.create(
                character_id=2, character_name="Second", refresh_token_ciphertext="b"
            )

    assert EsiCharacter.objects.count() == 1


@pytest.mark.django_db
def test_a_character_with_a_token_is_connected():
    character = EsiCharacter.objects.create(
        character_id=1, character_name="Pilot", refresh_token_ciphertext="ciphertext"
    )

    assert character.is_connected is True


@pytest.mark.django_db
def test_a_character_without_a_token_is_not_connected():
    character = EsiCharacter.objects.create(character_id=1, character_name="Pilot")

    assert character.is_connected is False


@pytest.mark.django_db
def test_disconnect_clears_the_token_but_keeps_the_row():
    """The row survives so the page can say what went wrong and when."""
    character = EsiCharacter.objects.create(
        character_id=1, character_name="Pilot", refresh_token_ciphertext="ciphertext"
    )

    character.disconnect("SSO rejected the refresh token.")

    reloaded = EsiCharacter.current()
    assert reloaded is not None
    assert reloaded.is_connected is False
    assert reloaded.character_name == "Pilot"
    assert "rejected" in reloaded.last_error


@pytest.mark.django_db
def test_disconnect_truncates_an_oversized_reason():
    """last_error is a CharField; an upstream message can be arbitrarily long.

    The same lesson as the quote `failures` field, where one oversized line
    aborted an entire snapshot.
    """
    character = EsiCharacter.objects.create(
        character_id=1, character_name="Pilot", refresh_token_ciphertext="ciphertext"
    )

    character.disconnect("x" * 500)

    assert len(EsiCharacter.current().last_error) == 255
