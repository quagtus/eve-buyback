"""The contract check admin page.

Rendered inside the admin shell and routed through admin.site.admin_view, so it
inherits the admin's authentication and permission checks rather than inventing
its own. Not translated: the admin is English by product decision, enforced by
AdminEnglishMiddleware.
"""

import secrets

from django.contrib import admin, messages
from django.shortcuts import redirect, render

from contracts.domain.gateway import ContractSourceError
from contracts.infrastructure.config import missing_esi_settings
from contracts.infrastructure.crypto import TokenCipherError
from contracts.infrastructure.sso import SsoError, make_pkce_pair
from contracts.models import EsiCharacter
from contracts.services import (
    MissingScopeError,
    NotLinkedError,
    build_sso,
    link_character,
    run_check,
)
from contracts.services import disconnect as disconnect_character

STATE_SESSION_KEY = "esi_oauth_state"
VERIFIER_SESSION_KEY = "esi_pkce_verifier"

CHECK_PATH = "/admin/contracts/check/"
TEMPLATE = "contracts/contract_check.html"


def _rows(result):
    """Flatten each verdict into what the template needs.

    Two things the template cannot work out for itself: Django templates cannot
    index a dict by a variable key, so the issuer name is resolved here; and the
    quote total is not stored on the verdict, only the delta is.
    """
    return [
        {
            "verdict": verdict,
            "contract": verdict.contract,
            "issuer_name": result.names.get(
                verdict.contract.issuer_id, str(verdict.contract.issuer_id)
            ),
            "quote_total": (
                None
                if verdict.price_delta is None
                else verdict.contract.price - verdict.price_delta
            ),
        }
        for verdict in result.verdicts
    ]


def contract_check(request):
    # each_context supplies what the admin shell needs to draw itself — most
    # visibly Unfold's sidebar navigation, which is simply absent from a plain
    # render() and leaves the operator with no way back out of the page.
    context = {
        **admin.site.each_context(request),
        "title": "Contract check",
        "missing_settings": missing_esi_settings(),
        "character": EsiCharacter.current(),
        "result": None,
        "rows": [],
        "error": "",
    }

    if request.method == "POST" and not context["missing_settings"]:
        try:
            result = run_check()
            context["result"] = result
            context["rows"] = _rows(result)
        except NotLinkedError:
            # Not an error: the page already renders the connect panel.
            pass
        except (SsoError, TokenCipherError, ContractSourceError) as exc:
            context["error"] = str(exc)
        # Reload: a failed refresh may have just cleared the credential, and the
        # page has to show the disconnected state rather than a stale one.
        context["character"] = EsiCharacter.current()

    return render(request, TEMPLATE, context)


def link(request):
    if missing_esi_settings():
        return redirect(CHECK_PATH)

    state = secrets.token_urlsafe(32)
    verifier, challenge = make_pkce_pair()
    request.session[STATE_SESSION_KEY] = state
    request.session[VERIFIER_SESSION_KEY] = verifier

    return redirect(build_sso().authorize_url(state=state, code_challenge=challenge))


def callback(request):
    # Popped, not read: a state value is single use, so a replayed callback
    # cannot be accepted a second time.
    expected = request.session.pop(STATE_SESSION_KEY, "")
    verifier = request.session.pop(VERIFIER_SESSION_KEY, "")
    received = request.GET.get("state", "")

    if not expected or not received or not secrets.compare_digest(expected, received):
        messages.error(
            request, "The SSO callback state did not match. Start the login again."
        )
        return redirect(CHECK_PATH)

    code = request.GET.get("code", "")
    if not code:
        reason = (
            request.GET.get("error_description")
            or request.GET.get("error")
            or "no reason given"
        )
        messages.error(request, f"SSO returned no authorization code: {reason}")
        return redirect(CHECK_PATH)

    try:
        character = link_character(code=code, code_verifier=verifier)
    except (SsoError, TokenCipherError, MissingScopeError) as exc:
        messages.error(request, str(exc))
        return redirect(CHECK_PATH)

    messages.success(request, f"Linked {character.character_name}.")
    return redirect(CHECK_PATH)


def disconnect(request):
    if request.method == "POST":
        disconnect_character()
        messages.success(request, "Character disconnected.")
    return redirect(CHECK_PATH)
