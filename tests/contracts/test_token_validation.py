"""Local JWT validation.

CCP has /v2/oauth/verify on a deprecation path and recommends validating the
token client-side against the published JWKS, which is what this does.

jwt.PyJWKClient fetches over urllib, not requests, so `responses` cannot
intercept it. The signing key is injected instead — which also means the
bad-signature test exercises real signature verification rather than a mock.
"""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from contracts.infrastructure.sso import DEFAULT_SCOPES, SsoError, TokenValidator

CLIENT_ID = "test-client-id"
CHARACTER_ID = 2112625428


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(private_key, **overrides):
    claims = {
        "sub": f"CHARACTER:EVE:{CHARACTER_ID}",
        "name": "Test Pilot",
        "scp": [DEFAULT_SCOPES],
        "aud": [CLIENT_ID, "EVE Online"],
        "iss": "login.eveonline.com",
        "iat": int(time.time()),
        "exp": int(time.time()) + 1199,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


class StubJwks:
    """Stands in for jwt.PyJWKClient, which is not our code to test."""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._public_key)


def build_validator(private_key):
    return TokenValidator(
        client_id=CLIENT_ID, jwks_client=StubJwks(private_key.public_key())
    )


def test_a_valid_token_yields_the_character_identity(signing_key):
    identity = build_validator(signing_key).identity(make_token(signing_key))

    assert identity.character_id == CHARACTER_ID
    assert identity.character_name == "Test Pilot"
    assert identity.scopes == (DEFAULT_SCOPES,)


def test_a_token_signed_by_the_wrong_key_is_rejected(signing_key, other_key):
    """Real signature verification: the token is signed with a key the
    validator does not trust."""
    token = make_token(other_key)

    with pytest.raises(SsoError):
        build_validator(signing_key).identity(token)


def test_a_token_for_another_client_is_rejected(signing_key):
    """Without the audience check, a token minted for any EVE app would pass."""
    token = make_token(signing_key, aud=["someone-elses-client", "EVE Online"])

    with pytest.raises(SsoError):
        build_validator(signing_key).identity(token)


def test_an_expired_token_is_rejected(signing_key):
    token = make_token(signing_key, exp=int(time.time()) - 60)

    with pytest.raises(SsoError):
        build_validator(signing_key).identity(token)


def test_a_token_with_no_expiry_is_rejected(signing_key):
    """options={"require": [...]} is what enforces this; a token without exp
    would otherwise validate forever."""
    claims = {
        "sub": f"CHARACTER:EVE:{CHARACTER_ID}",
        "name": "Test Pilot",
        "scp": [DEFAULT_SCOPES],
        "aud": [CLIENT_ID, "EVE Online"],
        "iss": "login.eveonline.com",
    }
    token = jwt.encode(claims, signing_key, algorithm="RS256")

    with pytest.raises(SsoError):
        build_validator(signing_key).identity(token)


def test_the_bare_host_issuer_is_accepted(signing_key):
    """CCP has issued both forms. Accepting only the URL breaks with no warning."""
    token = make_token(signing_key, iss="login.eveonline.com")

    assert build_validator(signing_key).identity(token).character_id == CHARACTER_ID


def test_the_url_form_issuer_is_accepted(signing_key):
    token = make_token(signing_key, iss="https://login.eveonline.com")

    assert build_validator(signing_key).identity(token).character_id == CHARACTER_ID


def test_an_unknown_issuer_is_rejected(signing_key):
    token = make_token(signing_key, iss="https://login.evil.example")

    with pytest.raises(SsoError) as exc:
        build_validator(signing_key).identity(token)

    assert "issuer" in str(exc.value).lower()


def test_an_unexpected_subject_format_is_rejected(signing_key):
    """A corporation or an unfamiliar prefix must not be read as a character id."""
    token = make_token(signing_key, sub="CORPORATION:EVE:98000001")

    with pytest.raises(SsoError) as exc:
        build_validator(signing_key).identity(token)

    assert "subject" in str(exc.value).lower()


def test_a_non_numeric_character_id_is_rejected(signing_key):
    token = make_token(signing_key, sub="CHARACTER:EVE:not-a-number")

    with pytest.raises(SsoError) as exc:
        build_validator(signing_key).identity(token)

    assert "subject" in str(exc.value).lower()


def test_a_wrong_prefix_whose_tail_is_numeric_is_rejected(signing_key):
    """Pins the prefix guard specifically, not the int() fallback behind it.

    "EVE:CHARACTER:12345" is exactly as long as the real prefix, so slicing it
    blindly yields a parseable 12345. Without the startswith check this would be
    accepted as character 12345 — a wrong id read out of a malformed subject.
    """
    token = make_token(signing_key, sub="EVE:CHARACTER:12345")

    with pytest.raises(SsoError) as exc:
        build_validator(signing_key).identity(token)

    assert "subject" in str(exc.value).lower()


def test_a_single_scope_arriving_as_a_bare_string_is_normalised(signing_key):
    """SSO returns scp as a string when exactly one scope was granted."""
    token = make_token(signing_key, scp=DEFAULT_SCOPES)

    assert build_validator(signing_key).identity(token).scopes == (DEFAULT_SCOPES,)


def test_a_jwks_fetch_failure_is_an_sso_error(signing_key):
    class FailingJwks:
        def get_signing_key_from_jwt(self, token):
            raise jwt.PyJWKClientError("could not fetch keys")

    validator = TokenValidator(client_id=CLIENT_ID, jwks_client=FailingJwks())

    with pytest.raises(SsoError):
        validator.identity(make_token(signing_key))
