"""Application layer: wires SSO, the contract gateway, quotes, and verification.

Collaborators are injectable so the tests exercise the real sequencing without
the network. The build_* helpers are the production wiring.
"""

from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from buyback.models import Quote
from contracts.domain.contract import STATUS_OUTSTANDING, QuoteLine, QuoteSnapshot
from contracts.domain.verdict import ContractVerdict
from contracts.domain.verification import verify_all
from contracts.infrastructure.crypto import TokenCipher, TokenCipherError
from contracts.infrastructure.esi import EsiContractGateway
from contracts.infrastructure.sso import (
    EveSso,
    SsoError,
    TokenRejected,
    TokenValidator,
)
from contracts.models import EsiCharacter


class NotLinkedError(RuntimeError):
    """No character is linked, or its credential has been cleared."""


class MissingScopeError(RuntimeError):
    """The login succeeded but did not grant permission to read contracts."""


@dataclass(frozen=True)
class CheckResult:
    verdicts: tuple[ContractVerdict, ...]
    names: dict[int, str]
    checked_at: datetime

    @property
    def ready_count(self) -> int:
        return sum(1 for verdict in self.verdicts if verdict.is_acceptable)

    @property
    def attention_count(self) -> int:
        return len(self.verdicts) - self.ready_count


def build_sso() -> EveSso:
    return EveSso(
        client_id=settings.ESI_CLIENT_ID,
        client_secret=settings.ESI_CLIENT_SECRET,
        callback_url=settings.ESI_CALLBACK_URL,
        user_agent=settings.ESI_USER_AGENT,
        scopes=settings.ESI_SCOPES,
    )


def build_validator() -> TokenValidator:
    return TokenValidator(client_id=settings.ESI_CLIENT_ID)


def build_gateway() -> EsiContractGateway:
    return EsiContractGateway(user_agent=settings.ESI_USER_AGENT)


def build_cipher() -> TokenCipher:
    return TokenCipher(settings.ESI_TOKEN_KEY)


def _load_quotes(codes) -> dict[str, QuoteSnapshot]:
    """One query for every quote any contract claims to fulfil."""
    wanted = {code for code in codes if code}
    if not wanted:
        return {}
    return {
        quote.code: QuoteSnapshot(
            code=quote.code,
            total_value=quote.total_value,
            created_at=quote.created_at,
            contract_days=quote.contract_days,
            lines=tuple(
                QuoteLine(type_id=item.type_id, quantity=item.quantity)
                for item in quote.items.all()
            ),
        )
        for quote in Quote.objects.filter(code__in=wanted).prefetch_related("items")
    }


def _revoke_quietly(sso: EveSso, cipher: TokenCipher, ciphertext: str) -> None:
    """Tidy up the replaced credential without letting it block the new login."""
    try:
        sso.revoke(cipher.decrypt(ciphertext))
    except (SsoError, TokenCipherError):
        pass


def link_character(
    *, code: str, code_verifier: str, sso=None, validator=None, cipher=None
) -> EsiCharacter:
    sso = sso or build_sso()
    # Built first: a missing or malformed ESI_TOKEN_KEY should fail before the
    # authorization code is spent, because a code cannot be reused.
    cipher = cipher or build_cipher()

    tokens = sso.exchange_code(code, code_verifier)
    identity = (validator or build_validator()).identity(tokens.access_token)

    # Compare what was asked for against what came back, rather than naming a
    # scope here: which scope grants contracts is a deployment question, settled
    # by ESI_SCOPES and by what the application at CCP actually carries.
    granted = set(identity.scopes)
    withheld = [scope for scope in sso.requested_scopes if scope not in granted]
    if withheld:
        # Usually the application itself was registered without the scope, in
        # which case SSO never offered it and re-authorising cannot help.
        raise MissingScopeError(
            f"The login granted {', '.join(identity.scopes) or 'no scopes'}, "
            f"withholding {', '.join(withheld)}. Add the missing scope to your "
            "application at developers.eveonline.com, save it, then connect again."
        )

    character = EsiCharacter.current() or EsiCharacter()
    replacing_another = (
        character.pk
        and character.is_connected
        and character.character_id != identity.character_id
    )
    if replacing_another:
        _revoke_quietly(sso, cipher, character.refresh_token_ciphertext)

    character.character_id = identity.character_id
    character.character_name = identity.character_name
    character.scopes = " ".join(identity.scopes)
    character.refresh_token_ciphertext = cipher.encrypt(tokens.refresh_token)
    character.linked_at = timezone.now()
    character.last_error = ""
    character.save()
    return character


def run_check(*, gateway=None, sso=None, cipher=None) -> CheckResult:
    character = EsiCharacter.current()
    if character is None or not character.is_connected:
        raise NotLinkedError("No EVE character is linked.")

    sso = sso or build_sso()
    cipher = cipher or build_cipher()
    gateway = gateway or build_gateway()

    try:
        refresh_token = cipher.decrypt(character.refresh_token_ciphertext)
    except TokenCipherError as exc:
        character.disconnect(str(exc))
        raise

    try:
        tokens = sso.refresh(refresh_token)
    except TokenRejected as exc:
        character.disconnect(str(exc))
        raise

    # Persist the rotated token immediately, before anything that can fail: SSO
    # may already have invalidated the one just submitted, so losing this write
    # leaves the link permanently dead. Every later failure is recoverable.
    character.refresh_token_ciphertext = cipher.encrypt(tokens.refresh_token)
    character.save(update_fields=["refresh_token_ciphertext"])

    contracts = tuple(
        contract
        for contract in gateway.fetch_contracts(
            character_id=character.character_id, access_token=tokens.access_token
        )
        if contract.status == STATUS_OUTSTANDING
        and contract.issuer_id != character.character_id
    )

    quotes_by_code = _load_quotes({contract.quote_code for contract in contracts})

    items_by_contract_id = {}
    for contract in contracts:
        if contract.quote_code in quotes_by_code:
            items_by_contract_id[contract.contract_id] = gateway.fetch_items(
                character_id=character.character_id,
                contract_id=contract.contract_id,
                access_token=tokens.access_token,
            )

    verdicts = verify_all(
        contracts,
        quotes_by_code,
        items_by_contract_id,
        character_id=character.character_id,
    )
    names = gateway.resolve_names({verdict.contract.issuer_id for verdict in verdicts})

    character.last_checked_at = timezone.now()
    character.last_error = ""
    character.save(update_fields=["last_checked_at", "last_error"])

    return CheckResult(
        verdicts=verdicts, names=names, checked_at=character.last_checked_at
    )


def disconnect() -> None:
    character = EsiCharacter.current()
    if character is not None:
        character.disconnect("Disconnected by the operator.")
