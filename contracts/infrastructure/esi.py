"""ESI implementation of ContractSourceGateway.

Schema verified against https://esi.evetech.net/meta/openapi.json (OpenAPI 3.1):

  GET /characters/{id}/contracts
      scope esi-contracts.read_character_contracts.v1
      paginated by ?page=N, total in the X-Pages RESPONSE HEADER
      title == the in-game contract Description
      price == the ISK the acceptor pays (item exchange and auctions)
      returns contracts the character issued, accepted, or was assigned,
      and only those under 30 days old unless status is in_progress

  GET /characters/{id}/contracts/{cid}/items
      not paginated
      is_included false == the issuer is ASKING FOR the item

  POST /universe/names
      unauthenticated, batched, best effort here

Every operation additionally requires an X-Compatibility-Date header. It is
declared required on the parameters of each path; that is easy to miss when
reading the spec, because the parameters arrive as $ref entries and a listing
that does not dereference them shows five nameless headers.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests

from contracts.domain.contract import ContractItemLine, ContractSnapshot
from contracts.domain.gateway import ContractSourceError, ScopeRejected

BASE_URL = "https://esi.evetech.net"
TIMEOUT_SECONDS = 30

# X-Compatibility-Date is `required: true` on every ESI operation: it pins which
# revision of the API answers, so ESI can change shapes without breaking callers.
# Pinned deliberately rather than tracking whatever is newest — a silent bump is
# exactly the breakage the header exists to prevent. CCP publishes the accepted
# values at https://esi.evetech.net/meta/compatibility-dates; moving forward means
# re-reading the spec for the endpoints below, then changing this.
DEFAULT_COMPATIBILITY_DATE = "2026-08-04"

# A sanity bound on X-Pages. A wrong or hostile header should not turn one click
# into an unbounded request loop.
MAX_PAGES = 50


def _parse_datetime(value: str) -> datetime:
    """ESI returns RFC 3339 with a literal Z, which fromisoformat rejects
    before Python 3.11. Normalising keeps this independent of the runtime."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _esi_error(response) -> str:
    """ESI's own message for a failure, which is usually the whole diagnosis."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200].strip()
    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("message") or "")[:300]
    return ""


def _authorization_error(response) -> ContractSourceError:
    """Classify a 401 or 403 from ESI.

    A token that lacks the scope is answered with 401 — not 403 — and the body
    names the scope it wanted, verified against the live endpoint. That
    distinction matters because the fixes differ: a missing scope means ESI_SCOPES
    and the application at CCP need to agree with what ESI asked for, whereas an
    expired token just needs re-linking.
    """
    detail = _esi_error(response)
    if "scope" in detail.lower():
        return ScopeRejected(
            f"{detail}. The linked token does not carry that scope: set ESI_SCOPES "
            "to it, make sure it is ticked on your application at "
            "developers.eveonline.com, then connect the character again."
        )
    return ContractSourceError(
        f"ESI refused the request ({response.status_code}): "
        f"{detail or 'no detail given'}. Try connecting the character again."
    )


def _int_header(response, name: str, default: int) -> int:
    try:
        return int(response.headers.get(name, default))
    except (TypeError, ValueError):
        return default


class EsiContractGateway:
    def __init__(
        self,
        *,
        user_agent: str,
        base_url: str = BASE_URL,
        compatibility_date: str = DEFAULT_COMPATIBILITY_DATE,
    ):
        self._user_agent = user_agent
        self._base_url = base_url.rstrip("/")
        self._compatibility_date = compatibility_date

    def _headers(self, **extra) -> dict:
        """Headers every ESI call needs, whether or not it is authenticated."""
        return {
            "Accept": "application/json",
            "User-Agent": self._user_agent,
            "X-Compatibility-Date": self._compatibility_date,
            **extra,
        }

    def fetch_contracts(self, *, character_id: int, access_token: str):
        path = f"/characters/{character_id}/contracts"
        rows: list[dict] = []
        page = 1
        total_pages = 1
        while page <= total_pages and page <= MAX_PAGES:
            response = self._get(path, access_token=access_token, params={"page": page})
            rows.extend(self._json(response))
            total_pages = _int_header(response, "X-Pages", default=1)
            page += 1
        return tuple(self._to_contract(row) for row in rows)

    def fetch_items(self, *, character_id: int, contract_id: int, access_token: str):
        response = self._get(
            f"/characters/{character_id}/contracts/{contract_id}/items",
            access_token=access_token,
        )
        try:
            return tuple(
                ContractItemLine(
                    type_id=int(row["type_id"]),
                    quantity=int(row["quantity"]),
                    is_included=bool(row["is_included"]),
                    is_singleton=bool(row["is_singleton"]),
                )
                for row in self._json(response)
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ContractSourceError(
                f"Unexpected contract item payload from ESI: {exc}"
            ) from exc

    def resolve_names(self, ids) -> dict[int, str]:
        """Best effort. Issuer names are cosmetic; a failure here must not fail
        the check, so the caller falls back to showing the raw id."""
        wanted = sorted({int(value) for value in ids if value})
        if not wanted:
            return {}
        try:
            response = requests.post(
                f"{self._base_url}/universe/names",
                json=wanted,
                headers=self._headers(),
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return {
                int(row["id"]): row.get("name") or str(row["id"])
                for row in response.json()
            }
        except (
            requests.RequestException,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return {}

    def _get(self, path: str, *, access_token: str, params: dict | None = None):
        try:
            response = requests.get(
                f"{self._base_url}{path}",
                params=params,
                headers=self._headers(Authorization=f"Bearer {access_token}"),
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise ContractSourceError(f"ESI request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise _authorization_error(response)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ContractSourceError(
                f"ESI returned {response.status_code}: {_esi_error(response) or exc}"
            ) from exc
        return response

    def _json(self, response):
        # parse_float=Decimal so ISK never round-trips through a binary float,
        # the same precaution as the Janice adapter.
        try:
            return response.json(parse_float=Decimal)
        except ValueError as exc:
            raise ContractSourceError("ESI returned a non-JSON response") from exc

    def _to_contract(self, row: dict) -> ContractSnapshot:
        # A 200 is not a guarantee of shape. Everything that walks the payload is
        # wrapped so a surprise becomes a ContractSourceError the view already
        # knows how to render, not a 500.
        try:
            return ContractSnapshot(
                contract_id=int(row["contract_id"]),
                title=row.get("title") or "",
                contract_type=row.get("type") or "unknown",
                status=row.get("status") or "unknown",
                price=Decimal(str(row.get("price") or 0)),
                issuer_id=int(row["issuer_id"]),
                assignee_id=int(row["assignee_id"]),
                date_issued=_parse_datetime(row["date_issued"]),
            )
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            InvalidOperation,
        ) as exc:
            raise ContractSourceError(
                f"Unexpected contract payload from ESI: {exc}"
            ) from exc
