"""EVE SSO: authorization, code exchange, refresh, revocation, token validation.

Endpoint URLs are the ones published at
https://login.eveonline.com/.well-known/oauth-authorization-server, which also
advertises code_challenge_methods_supported = ["S256"] and
client_secret_basic authentication.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import jwt
import requests

AUTHORIZE_URL = "https://login.eveonline.com/v2/oauth/authorize"
TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
JWKS_URL = "https://login.eveonline.com/oauth/jwks"
REVOKE_URL = "https://login.eveonline.com/v2/oauth/revoke"

CONTRACTS_SCOPE = "esi-contracts.read_character_contracts.v1"

TIMEOUT_SECONDS = 20

# CCP has issued the bare host as well as the URL form. Pinning only one breaks
# silently the moment they switch, so both are accepted.
VALID_ISSUERS = ("login.eveonline.com", "https://login.eveonline.com")

_SUBJECT_PREFIX = "CHARACTER:EVE:"


class SsoError(RuntimeError):
    """The SSO exchange failed or returned something unusable."""


class TokenRejected(SsoError):
    """The credential is no longer valid; the operator must log in again.

    Separate from SsoError because the recovery differs: this one is fixed by a
    re-login, whereas a bad client secret is fixed by editing the environment.
    """


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class CharacterIdentity:
    character_id: int
    character_name: str
    scopes: tuple[str, ...]


def make_pkce_pair() -> tuple[str, str]:
    """Return (verifier, S256 challenge).

    PKCE is used even though this is a confidential client with a secret: the
    project ships with DJANGO_SECURE_COOKIES=0, so a plain-HTTP self-host is a
    realistic deployment, and there an intercepted authorization code is a live
    credential.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _error_code(response) -> str:
    try:
        return response.json().get("error") or response.text[:200]
    except ValueError:
        return response.text[:200]


class EveSso:
    def __init__(
        self, *, client_id: str, client_secret: str, callback_url: str, user_agent: str
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._callback_url = callback_url
        self._user_agent = user_agent

    def authorize_url(self, *, state: str, code_challenge: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "redirect_uri": self._callback_url,
                "client_id": self._client_id,
                "scope": CONTRACTS_SCOPE,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    def exchange_code(self, code: str, code_verifier: str) -> TokenPair:
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
            }
        )

    def refresh(self, refresh_token: str) -> TokenPair:
        return self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    def revoke(self, refresh_token: str) -> None:
        try:
            response = requests.post(
                REVOKE_URL,
                data={"token_type_hint": "refresh_token", "token": refresh_token},
                auth=(self._client_id, self._client_secret),
                headers={"User-Agent": self._user_agent},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SsoError(f"Token revocation failed: {exc}") from exc

    def _token_request(self, data: dict) -> TokenPair:
        try:
            response = requests.post(
                TOKEN_URL,
                data=data,
                auth=(self._client_id, self._client_secret),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Host": "login.eveonline.com",
                    "User-Agent": self._user_agent,
                },
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise SsoError(f"SSO token request failed: {exc}") from exc

        if response.status_code in (400, 401):
            detail = _error_code(response)
            if detail == "invalid_grant":
                raise TokenRejected(
                    "SSO rejected the credential. Link the character again."
                )
            raise SsoError(f"SSO rejected the request: {detail}")

        try:
            response.raise_for_status()
            payload = response.json()
            return TokenPair(
                access_token=payload["access_token"],
                refresh_token=payload["refresh_token"],
            )
        except requests.RequestException as exc:
            raise SsoError(f"SSO token request failed: {exc}") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise SsoError(f"SSO returned an unexpected token payload: {exc}") from exc


class TokenValidator:
    """Validates SSO access tokens against the published JWKS.

    jwks_client is injectable because jwt.PyJWKClient fetches over urllib, which
    the test suite's HTTP mocking cannot intercept — and because the JWKS
    transport is PyJWT's code, not ours.
    """

    def __init__(self, *, client_id: str, jwks_client=None, jwks_url: str = JWKS_URL):
        self._client_id = client_id
        self._jwks_client = jwks_client or jwt.PyJWKClient(jwks_url, cache_keys=True)

    def identity(self, access_token: str) -> CharacterIdentity:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(access_token)
            claims = jwt.decode(
                access_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        # PyJWKClientError subclasses PyJWTError; OSError covers a urllib
        # transport failure reaching the JWKS endpoint.
        except (jwt.PyJWTError, OSError) as exc:
            raise SsoError(f"The SSO access token failed validation: {exc}") from exc

        # Validated here rather than through jwt.decode(issuer=...), which only
        # accepts a collection in recent PyJWT versions.
        issuer = claims.get("iss")
        if issuer not in VALID_ISSUERS:
            raise SsoError(f"Unexpected token issuer: {issuer!r}")

        subject = claims.get("sub") or ""
        if not subject.startswith(_SUBJECT_PREFIX):
            raise SsoError(f"Unexpected token subject: {subject!r}")
        try:
            character_id = int(subject[len(_SUBJECT_PREFIX):])
        except ValueError as exc:
            raise SsoError(f"Unexpected token subject: {subject!r}") from exc

        scopes = claims.get("scp") or ()
        if isinstance(scopes, str):
            # SSO returns a bare string when exactly one scope was granted.
            scopes = (scopes,)

        return CharacterIdentity(
            character_id=character_id,
            character_name=claims.get("name") or "",
            scopes=tuple(scopes),
        )
