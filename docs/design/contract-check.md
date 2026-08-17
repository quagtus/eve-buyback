# Contract check

An admin page that lists the operator's outstanding in-game contracts and marks
the ones that are safe to accept, by verifying each against the quote it claims
to be fulfilling.

## Purpose

A seller gets a quote at `/q/<code>/`, then creates an item exchange contract in
EVE with the quote code as the contract description. The operator ends up with a
pile of pending contracts and no way to tell, without opening each one, which
ones actually match what was quoted.

This page closes that loop. One click reads the operator's pending contracts
through ESI, matches each to its quote, and marks a contract green only when the
code, the price, and the contract's actual contents all agree.

Scope: one authenticated character, read-only. Logging in as a different
character replaces the stored one. The page never accepts, rejects, or modifies
a contract — accepting still happens in the game client.

## ESI facts this depends on (verified)

Verified against `https://esi.evetech.net/meta/openapi.json` (OpenAPI 3.1,
server `https://esi.evetech.net`) and
`https://login.eveonline.com/.well-known/oauth-authorization-server`.

**SSO endpoints**, read from the well-known document rather than assumed:

| Purpose | URL |
|---|---|
| Authorize | `https://login.eveonline.com/v2/oauth/authorize` |
| Token | `https://login.eveonline.com/v2/oauth/token` |
| JWKS | `https://login.eveonline.com/oauth/jwks` |
| Revoke | `https://login.eveonline.com/v2/oauth/revoke` |

`code_challenge_methods_supported` is `["S256"]` and
`token_endpoint_auth_methods_supported` includes `client_secret_basic`, so the
confidential-client flow with PKCE on top is fully supported.

**`GET /characters/{character_id}/contracts`** — scope
`esi-contracts.read_character_contracts.v1`.

- Paginated by a `page` query parameter; the total is in the **`X-Pages`
  response header**, not in the body.
- Returns contracts "available to a character, only if the character is issuer,
  acceptor or assignee", and only those "no older than 30 days, or if the status
  is `in_progress`". Both facts are load-bearing: we must filter by role
  ourselves, and a contract for a quote older than a month may simply not appear.
- `status` is one of `outstanding`, `in_progress`, `finished_issuer`,
  `finished_contractor`, `finished`, `cancelled`, `rejected`, `failed`,
  `deleted`, `reversed`. Pending is **`outstanding`**.
- `type` is one of `unknown`, `item_exchange`, `auction`, `courier`, `loan`.
- **`title` is the in-game Description field.** This is where the quote code
  lands, and the name difference is the single most confusing part of the API.
- **`price` is the ISK the acceptor pays.** A seller handing over items and
  asking to be paid produces a `price`, which is what the quote page's "I will
  receive" line tells them to enter. `reward` is documented as couriers-only and
  is not part of the match.

**`GET /characters/{character_id}/contracts/{contract_id}/items`** — same scope,
**not paginated**.

- Required fields: `record_id`, `type_id`, `quantity`, `is_singleton`,
  `is_included`.
- **`is_included` is false when the issuer is *asking for* that item** rather
  than submitting it. Every line of a legitimate buyback contract must be true;
  a false line means the seller is demanding goods from the operator.
- `raw_quantity` is `-1` for a singleton, and for blueprints distinguishes an
  original from a copy.

**Tokens.** The access token is a JWT valid for roughly 1200 seconds. A refresh
returns a refresh token that **may differ from the one submitted, and the
submitted one is then invalid**. Storage must be overwritten on every refresh;
treating the refresh token as a constant breaks the integration about twenty
minutes after it is set up.

`/v2/oauth/verify` still exists but CCP has it on a deprecation path and
recommends validating the JWT locally instead, which is what we do.

## Structure

A new `contracts` app, laid out like the existing ones: pure domain, adapters
behind a port, thin models.

```
contracts/
  domain/                 no Django imports
    contract.py           ContractSnapshot, ContractItemLine, QuoteSnapshot
    verdict.py            Problem, Warning, ItemDiff, ContractVerdict
    verification.py       verify(contract, quote, items) -> ContractVerdict
    gateway.py            ContractSourceGateway protocol, ContractSourceError
  infrastructure/
    sso.py                authorize URL, code exchange, refresh, JWT validation
    esi.py                EsiContractGateway
    crypto.py             TokenCipher
  models.py               EsiCharacter
  services.py             orchestration
  views.py                link, callback, check, disconnect
  management/commands/generate_esi_key.py
```

`ContractSourceGateway` mirrors `PriceAppraisalGateway`: the domain declares what
it needs from a contract source, and `EsiContractGateway` is one
implementation. Corporation contracts, or any other source, become a second
adapter rather than a change to the verification logic.

Verification is a pure function over frozen dataclasses. It touches neither the
ORM, the network, nor the clock — every comparison is between values carried on
the snapshots, including the staleness check, which compares the contract's issue
date against the quote's own frozen window rather than against "now". The entire
match truth table is therefore unit-testable without a database.

## Data model

One new table, one row.

```python
class EsiCharacter(models.Model):
    """The single authenticated character whose contracts get checked."""

    character_id = models.BigIntegerField()
    character_name = models.CharField(max_length=255)
    refresh_token_ciphertext = models.TextField(blank=True)
    scopes = models.TextField(blank=True)
    linked_at = models.DateTimeField()
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)
```

Singleton on `pk=1`, following `SiteConfig` — logging in as another character
overwrites the row, which is the stated requirement. `character_id` is a normal
field rather than the primary key precisely because it changes on re-login.

Nothing about a check is persisted. The page is a live view: no contract table,
no cached results, no history. Adding history later means a new table, not a
change to anything here.

### Token storage

The refresh token is encrypted with Fernet before it is written. The key comes
from `ESI_TOKEN_KEY`, so a leaked database dump or backup is not on its own
enough to read the operator's contracts. The client id and secret live in the
environment as plain text, alongside `JANICE_API_KEY` — consistent with the
existing rule that credentials do not go in the database.

`TokenCipher` is a small explicit wrapper rather than a custom encrypted model
field: a field that transparently encrypts also silently breaks `filter()` and
migrations on that column, and hides an environment dependency inside the model
layer.

Losing or rotating `ESI_TOKEN_KEY` is recoverable. Decryption failure is treated
exactly like a rejected token: the row is marked disconnected and the page asks
for a re-login, which is one click.

## Linking a character

1. `GET /admin/contracts/link/` generates a `state` and a PKCE verifier, stores
   both in the session, and redirects to the authorize endpoint with scope
   `esi-contracts.read_character_contracts.v1`, `code_challenge_method=S256`.
2. `GET /admin/contracts/callback/` pops `state`, compares it with
   `secrets.compare_digest`, and exchanges the code using HTTP Basic auth plus
   the `code_verifier`. A missing or mismatched `state` aborts before any token
   is stored.
3. The returned access token is validated locally: RS256 against the JWKS
   endpoint, `aud` must contain the client id, and `iss` is accepted as **either
   `login.eveonline.com` or `https://login.eveonline.com`** — CCP has issued the
   bare host, and accepting only the URL form is a known way to break.
4. Claims give the identity: `sub` is `CHARACTER:EVE:<id>`, `name` is the
   character name, `scp` is the granted scopes. **If the contracts scope is
   absent from `scp`, the link is refused with an explanatory message** rather
   than stored and left to fail with a 403 on the first check.
5. The refresh token is encrypted and saved. If a different character was linked
   before, the old token is revoked first on a best-effort basis; a revoke
   failure is logged and does not block the new login.

Both views are wrapped in `admin.site.admin_view`, so they inherit the admin's
authentication and permission checks.

PKCE is used even though the client secret is available. The shipped default is
`DJANGO_SECURE_COOKIES=0`, so a plain-HTTP self-host is a realistic deployment,
and there an intercepted authorization code is a live credential. The cost is a
hash and one extra parameter.

## Checking

`POST /admin/contracts/check/` — a plain form post that re-renders the page. The
admin shell does not load HTMX (that is only in the public `base.html`), and a
full render needs no partial template and works with JavaScript disabled.

1. Load `EsiCharacter`, decrypt the refresh token, and exchange it for an access
   token. **The new refresh token is written back immediately.** The access token
   is never stored; it lives for the duration of this request. Refreshing on
   every check means the rotation path is exercised constantly rather than
   rarely.
2. Fetch all pages of the contracts endpoint, following `X-Pages`.
3. Keep contracts where `status == "outstanding"` and `issuer_id` is not the
   linked character, so contracts the operator issued drop out. Note that this
   endpoint only ever returns contracts where the character is issuer, acceptor
   or assignee — a contract a seller addressed to somebody else is not visible
   here at all, and cannot be reported as a problem (see Deliberate limitations).
4. Collect the titles and load the quotes in one query:
   `Quote.objects.filter(code__in=titles).prefetch_related("items")`.
5. Fetch items **only for contracts whose title matched a quote**. Unrelated
   contracts cost no extra requests.
6. Run `verify()` per contract and render.

Issuer names come from one batched, unauthenticated `POST /universe/names`,
best-effort — a failure there shows the raw ID rather than failing the check.

Titles are compared stripped and case-sensitively. The quote page already gives
sellers a copy button for the code, so an exact copy is the normal path; matching
case-insensitively would need collision handling for two codes differing only in
case.

## Verification rules

A verdict carries two severities. Problems block green; warnings annotate a green
row. Without that split, green would be so rare it would stop meaning anything —
a seller rounding the price down in the operator's favour should not read the
same as a seller swapping the items.

**Problems** — the contract is not safe to accept as-is:

| Key | Condition |
|---|---|
| `NO_MATCHING_QUOTE` | title matches no quote code |
| `DUPLICATE_QUOTE_CODE` | two outstanding contracts cite the same code |
| `WRONG_CONTRACT_TYPE` | `type != "item_exchange"` |
| `ASSIGNED_ELSEWHERE` | `assignee_id` is not the linked character — in practice this means assigned to the operator's corporation rather than to them, since a contract addressed to an unrelated character is not returned at all |
| `PRICE_ABOVE_QUOTE` | `price > quote.total_value` |
| `ITEMS_REQUESTED` | any line has `is_included == false` |
| `ITEM_MISSING` | a quote line is absent from the contract |
| `ITEM_EXTRA` | the contract contains a type the quote does not |
| `QUANTITY_MISMATCH` | quantities differ for a matched type |

**Warnings** — acceptable, but worth seeing:

| Key | Condition |
|---|---|
| `PRICE_BELOW_QUOTE` | `price < quote.total_value`; the delta is shown |
| `ASSEMBLED_ITEMS` | a line has `is_singleton == true`; Janice priced it packaged, and an assembled item may be damaged or fitted |
| `QUOTE_STALE` | `date_issued` is later than `created_at + contract_days`; the quote's frozen prices are older than the window it advertised |

Item comparison aggregates contract lines by `type_id` before comparing, because
a contract can carry the same type in several stacks. Two exclusions from that
aggregate:

- Lines with `is_included == false` are not counted as offered goods — they are
  the opposite. They raise `ITEMS_REQUESTED` and are listed separately, so they
  cannot accidentally satisfy a quote line.
- Quote lines with a null `type_id` — unparseable paste lines, which are always
  flagged and zero-valued — are ignored. They were never part of the offer, so
  requiring them in the contract would make every quote containing a typo
  impossible to fulfil.

Prices are compared as `Decimal`. ESI JSON is parsed with `parse_float=Decimal`,
the same precaution as the Janice adapter, where a float round-trip loses a cent
around 1e14. `price` is optional in the schema; an absent one is read as zero,
which lands as `PRICE_BELOW_QUOTE` — a contract asking nothing is in the
operator's favour, however odd it looks.

A verdict is acceptable when it has no problems. It is rendered green with a
"Ready" pill and a left border, never colour alone.

## Configuration

```
ESI_CLIENT_ID=
ESI_CLIENT_SECRET=
ESI_CALLBACK_URL=https://buyback.example.com/admin/contracts/callback/
ESI_TOKEN_KEY=
ESI_USER_AGENT=eve-buyback (you@example.com)
```

`ESI_CALLBACK_URL` is explicit rather than derived from the request. It must
match the registration at developers.eveonline.com exactly, and deriving it from
`build_absolute_uri` behind a TLS-terminating proxy is the usual cause of
`invalid_request: redirect_uri mismatch`.

`ESI_USER_AGENT` is sent on every ESI call; CCP asks third-party apps to identify
themselves with a contactable string.

`manage.py generate_esi_key` prints a Fernet key for `ESI_TOKEN_KEY`.

New dependencies: `PyJWT` for token validation and `cryptography` for Fernet.
`cryptography` arrives transitively with `PyJWT[crypto]` but is pinned explicitly
because `crypto.py` imports it directly.

## Failure modes

Every one of these renders as a panel or banner. None produces a 500.

| Condition | Behaviour |
|---|---|
| any required env var unset | "not configured" panel naming exactly which ones are missing |
| no character linked | connect panel; not an error |
| `state` missing or mismatched | rejected, no token stored |
| refresh returns `invalid_grant` | token is dead: clear the ciphertext, record `last_error`, show "disconnected — reconnect" |
| `ESI_TOKEN_KEY` changed or lost | decryption fails, same disconnected path |
| ESI 403 | scope revoked in-game; prompt to reconnect |
| ESI 5xx, timeout, connection error | error banner, link left intact, nothing mutated |
| unexpected payload shape | `ContractSourceError` naming the field that broke |
| the check is double-submitted | the button disables itself on submit |

The double-submit guard matters more than it looks: two concurrent refreshes with
the same rotating token leave one of them invalid, which disconnects the
integration. Recovery is one click of Reconnect.

It is deliberately not solved with a database lock. `select_for_update` around
the refresh would hold a transaction open across an HTTP call — the same mistake
already fixed in `generate_quote`, where a 30-second gateway call was moved
outside the atomic block.

## The page

Route `/admin/contracts/check/`, registered in `config/urls.py` next to
`/admin/pricing/summary/` and reachable from a new "Contracts" sidebar group in
`UNFOLD`.

The template extends the admin shell and keys its colours to `html.dark`, which
is what Unfold's theme toggle binds. Hardcoding light values is not a
hypothetical mistake — `pricing/rule_summary.html` shipped that way once and was
unreadable in dark mode.

States: not configured, not linked, linked and idle, results, error. The results
view leads with a count — "14 outstanding · 5 ready to accept · 9 need
attention" — and sorts acceptable contracts first, then newest first.

Columns: status pill, title linked to `/q/<code>/`, issuer, contract price, quote
total, delta, date issued, and the problem and warning list.

## Testing

Domain tests need no database and no network, and cover the truth table: exact
price, price under quote, price over quote, missing item, extra item, wrong
quantity, `is_included == false`, duplicate titles, unknown title, wrong contract
type, assignee mismatch, stale quote, multi-stack aggregation, and null-`type_id`
quote lines being ignored.

Infrastructure tests use `responses`, already a dependency:

- **The rotated refresh token is what ends up stored.** This is the highest-value
  test in the suite: get it wrong and the integration works perfectly until the
  first access token expires, then fails permanently.
- `X-Pages: 3` results in three requests and a concatenated result.
- Prices arrive as `Decimal`, never `float`.
- `invalid_grant` produces the disconnected state and clears the token.
- JWT validation, signed with a throwaway RSA key against a served fake JWKS: a
  good token yields the right character id; a bad signature, a wrong `aud`, and a
  missing scope are each rejected.

Crypto tests cover a round trip, a wrong key producing a clean domain error
rather than a stack trace, and a missing key refusing the link rather than
storing plaintext.

View tests cover the admin permission requirement, `state` rejection, and the
unconfigured page rendering a panel instead of a 500.

## Deliberate limitations

- **Character contracts only.** Contracts assigned to a corporation are not
  fetched; `SiteConfig.contract_to` naming a corporation is not supported. This
  is the first extension point — a corporation adapter behind the same port.
- **A misaddressed contract is invisible.** If a seller quotes correctly but
  contracts to the wrong character, this page cannot show it, because ESI only
  returns contracts the authenticated character is a party to. The seller has to
  notice and re-issue. Nothing in the design can work around it.
- **Contracts older than 30 days are not returned** by ESI unless their status is
  `in_progress`. Item exchange contracts expire well inside that window, so it
  does not affect pending ones in practice.
- **One character.** Verification takes a character id as an argument and does
  not otherwise know about the singleton, so multiple characters is a model
  change plus a selector, not a redesign.
- **No blueprint original/copy check.** `raw_quantity` distinguishes them and
  their values differ enormously, but the quote side has no equivalent signal.
  The `ASSEMBLED_ITEMS` warning covers it partially.
- **No accept action.** Accepting a contract is not possible through ESI; it
  happens in the client. `/ui/openwindow/contract` could open the contract in the
  running client, but it needs an additional scope and is not part of this work.
- **Nothing is remembered between checks**, so a contract accepted last week and
  a quote fulfilled twice on different days are both invisible. Same-check
  duplicates are caught by `DUPLICATE_QUOTE_CODE`.
