"""EVE SSO. Endpoints are the ones published at
https://login.eveonline.com/.well-known/oauth-authorization-server
"""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from contracts.infrastructure.sso import (
    CONTRACTS_SCOPE,
    REVOKE_URL,
    TOKEN_URL,
    EveSso,
    SsoError,
    TokenRejected,
    make_pkce_pair,
)

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
CALLBACK = "https://buyback.example.test/admin/contracts/callback/"


def build_sso():
    return EveSso(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        callback_url=CALLBACK,
        user_agent="eve-buyback tests",
    )


def test_pkce_challenge_is_the_base64url_sha256_of_the_verifier():
    """Getting this wrong produces "invalid_grant" at the exchange, with no hint."""
    verifier, challenge = make_pkce_pair()

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected
    assert "=" not in challenge


def test_pkce_pairs_are_not_reused():
    assert make_pkce_pair()[0] != make_pkce_pair()[0]


def test_the_authorize_url_carries_everything_sso_requires():
    url = build_sso().authorize_url(state="abc123", code_challenge="chal")
    query = parse_qs(urlparse(url).query)

    assert urlparse(url).netloc == "login.eveonline.com"
    assert query["response_type"] == ["code"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [CALLBACK]
    assert query["scope"] == [CONTRACTS_SCOPE]
    assert query["state"] == ["abc123"]
    assert query["code_challenge"] == ["chal"]
    assert query["code_challenge_method"] == ["S256"]


@responses.activate
def test_exchanging_a_code_returns_both_tokens():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 1199},
        status=200,
    )

    tokens = build_sso().exchange_code("the-code", "the-verifier")

    assert tokens.access_token == "access-1"
    assert tokens.refresh_token == "refresh-1"


@responses.activate
def test_the_exchange_sends_the_verifier_and_authenticates_with_basic_auth():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "a", "refresh_token": "r"},
        status=200,
    )

    build_sso().exchange_code("the-code", "the-verifier")

    request = responses.calls[0].request
    body = parse_qs(request.body)
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["the-code"]
    assert body["code_verifier"] == ["the-verifier"]

    expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert request.headers["Authorization"] == f"Basic {expected}"


@responses.activate
def test_invalid_grant_is_a_token_rejection_not_a_generic_error():
    """The caller reacts differently: TokenRejected means "ask for a re-login"."""
    responses.add(responses.POST, TOKEN_URL, json={"error": "invalid_grant"}, status=400)

    with pytest.raises(TokenRejected):
        build_sso().exchange_code("stale-code", "verifier")


@responses.activate
def test_other_client_errors_are_generic_sso_errors():
    """invalid_client means a misconfigured secret, which a re-login cannot fix."""
    responses.add(responses.POST, TOKEN_URL, json={"error": "invalid_client"}, status=401)

    with pytest.raises(SsoError) as exc:
        build_sso().exchange_code("code", "verifier")

    assert not isinstance(exc.value, TokenRejected)
    assert "invalid_client" in str(exc.value)


@responses.activate
def test_a_transport_failure_is_an_sso_error():
    # requests.ConnectionError, not the builtin: only the requests hierarchy
    # is what a real transport failure raises through this adapter.
    responses.add(
        responses.POST, TOKEN_URL, body=requests.ConnectionError("network is down")
    )

    with pytest.raises(SsoError):
        build_sso().exchange_code("code", "verifier")


@responses.activate
def test_a_token_payload_missing_the_refresh_token_is_an_sso_error():
    """A 200 is not a guarantee of shape, the same lesson as the Janice adapter."""
    responses.add(responses.POST, TOKEN_URL, json={"access_token": "only"}, status=200)

    with pytest.raises(SsoError) as exc:
        build_sso().exchange_code("code", "verifier")

    assert "unexpected" in str(exc.value).lower()


@responses.activate
def test_refreshing_sends_the_grant_type_and_the_stored_token():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "access-2", "refresh_token": "refresh-2"},
        status=200,
    )

    tokens = build_sso().refresh("refresh-1")

    body = parse_qs(responses.calls[0].request.body)
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["refresh-1"]
    assert tokens.access_token == "access-2"


@responses.activate
def test_a_refresh_returns_whatever_refresh_token_sso_sends_back():
    """SSO may rotate the refresh token and invalidate the one submitted.

    The caller has to persist what comes back. Returning the submitted token
    instead would work until the first rotation, then fail permanently.
    """
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "access-2", "refresh_token": "rotated-token"},
        status=200,
    )

    assert build_sso().refresh("original-token").refresh_token == "rotated-token"


@responses.activate
def test_a_rejected_refresh_token_raises_token_rejected():
    responses.add(responses.POST, TOKEN_URL, json={"error": "invalid_grant"}, status=400)

    with pytest.raises(TokenRejected):
        build_sso().refresh("dead-token")


@responses.activate
def test_revoking_posts_the_token_with_its_type_hint():
    responses.add(responses.POST, REVOKE_URL, status=200)

    build_sso().revoke("old-token")

    body = parse_qs(responses.calls[0].request.body)
    assert body["token"] == ["old-token"]
    assert body["token_type_hint"] == ["refresh_token"]


# Verified live: POSTing to the token endpoint with a wrong client secret returns
# 401 with content-type text/html and the SSO login page as the body — not a JSON
# error. Dumping that body verbatim produced "SSO rejected the request:
# <!DOCTYPE html> <html lang=..." which names neither the cause nor the fix.
HTML_ERROR_PAGE = (
    '\n<!DOCTYPE html>\n<html lang="en">\n<head>\n'
    '    <script src="https://sso-assets.eveonline.com/dist/lib-BKwMjlp5.prod.js"'
    ' defer type="module"></script>\n    <link rel="stylesheet" href="/x.css">\n'
)


@responses.activate
def test_an_html_401_blames_the_client_credentials_not_the_markup():
    responses.add(
        responses.POST,
        TOKEN_URL,
        body=HTML_ERROR_PAGE,
        status=401,
        content_type="text/html; charset=utf-8",
    )

    with pytest.raises(SsoError) as exc:
        build_sso().exchange_code("code", "verifier")

    message = str(exc.value)
    assert "ESI_CLIENT_SECRET" in message, "the message must name what to check"
    assert "<!DOCTYPE" not in message, "the HTML body must not be pasted into the error"
    assert "<script" not in message


@responses.activate
def test_an_html_401_is_not_mistaken_for_a_dead_refresh_token():
    """Bad credentials are fixed by editing the environment; a re-login cannot
    help, so this must not surface as TokenRejected."""
    responses.add(
        responses.POST,
        TOKEN_URL,
        body=HTML_ERROR_PAGE,
        status=401,
        content_type="text/html; charset=utf-8",
    )

    with pytest.raises(SsoError) as exc:
        build_sso().refresh("some-token")

    assert not isinstance(exc.value, TokenRejected)


@responses.activate
def test_a_json_error_description_is_included():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={
            "error": "invalid_request",
            "error_description": "Invalid redirect_uri",
        },
        status=400,
    )

    with pytest.raises(SsoError) as exc:
        build_sso().exchange_code("code", "verifier")

    assert "invalid_request" in str(exc.value)
    assert "Invalid redirect_uri" in str(exc.value)
