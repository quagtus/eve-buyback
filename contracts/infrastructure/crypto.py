"""Symmetric encryption for the stored SSO refresh token.

An explicit wrapper rather than a custom encrypted model field: a field that
transparently encrypts also silently breaks filter() and migrations on that
column, and buries an environment dependency inside the model layer.
"""

from cryptography.fernet import Fernet, InvalidToken


class TokenCipherError(RuntimeError):
    """The token could not be encrypted or decrypted with the configured key."""


class TokenCipher:
    def __init__(self, key: str | bytes):
        if not key:
            raise TokenCipherError(
                "ESI_TOKEN_KEY is not set. Generate one with "
                "`manage.py generate_esi_key` and add it to the environment."
            )
        material = key.encode() if isinstance(key, str) else key
        try:
            self._fernet = Fernet(material)
        except (ValueError, TypeError) as exc:
            # binascii.Error subclasses ValueError, which is what a
            # non-base64 key produces.
            raise TokenCipherError(
                f"ESI_TOKEN_KEY is not a valid Fernet key: {exc}"
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, ValueError, TypeError) as exc:
            raise TokenCipherError(
                "The stored refresh token could not be decrypted — ESI_TOKEN_KEY "
                "has probably changed. Re-link the character."
            ) from exc
