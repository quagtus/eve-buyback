"""The refresh token is encrypted so a database dump cannot read contracts.

Every failure path here has to be recoverable: losing the key must produce a
"re-link the character" prompt, never a stack trace and never silent plaintext.
"""

import pytest
from cryptography.fernet import Fernet

from contracts.infrastructure.crypto import TokenCipher, TokenCipherError

TOKEN = "gEyM1c9wRQ-a-refresh-token-from-sso"


def test_a_token_survives_a_round_trip():
    cipher = TokenCipher(Fernet.generate_key().decode())

    assert cipher.decrypt(cipher.encrypt(TOKEN)) == TOKEN


def test_the_ciphertext_does_not_contain_the_token():
    """Otherwise the encryption is decorative."""
    cipher = TokenCipher(Fernet.generate_key().decode())

    assert TOKEN not in cipher.encrypt(TOKEN)


def test_a_missing_key_is_refused_rather_than_storing_plaintext():
    with pytest.raises(TokenCipherError) as exc:
        TokenCipher("")

    assert "generate_esi_key" in str(exc.value)


def test_a_malformed_key_is_reported_clearly():
    with pytest.raises(TokenCipherError) as exc:
        TokenCipher("not-a-fernet-key")

    assert "ESI_TOKEN_KEY" in str(exc.value)


def test_decrypting_with_the_wrong_key_asks_for_a_re_link():
    """The recovery path when ESI_TOKEN_KEY is rotated or lost."""
    ciphertext = TokenCipher(Fernet.generate_key().decode()).encrypt(TOKEN)
    other = TokenCipher(Fernet.generate_key().decode())

    with pytest.raises(TokenCipherError) as exc:
        other.decrypt(ciphertext)

    assert "re-link" in str(exc.value).lower()


def test_decrypting_garbage_is_a_token_cipher_error_not_a_crash():
    cipher = TokenCipher(Fernet.generate_key().decode())

    with pytest.raises(TokenCipherError):
        cipher.decrypt("this is not ciphertext at all")


def test_accepts_a_key_as_bytes_or_str():
    """Environment variables arrive as str; Fernet.generate_key() returns bytes."""
    key = Fernet.generate_key()

    assert TokenCipher(key).decrypt(TokenCipher(key.decode()).encrypt(TOKEN)) == TOKEN
