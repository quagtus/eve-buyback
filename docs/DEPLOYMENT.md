# Deployment

## 1. Local development

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_catalog
docker compose exec web python manage.py createsuperuser
```

- `docker-compose.yml` runs `runserver` with the source bind-mounted, so
  code edits reload live. This is the development setup only — see §3 for
  production.
- `seed_catalog` is **manual and not run automatically**. It downloads
  ~14 MB of reference data from EVERef and imports roughly 27,000 item
  types (categories, groups, types). It takes a minute or two depending on
  your connection. The admin (rule pickers, blacklist) and quote generation
  (type → group → category classification) both depend on this data being
  present, so run it before relying on the app for real.

The app is now at `http://localhost:8000/`, admin at `/admin/`.

## 2. Janice API key

The app cannot generate quotes without a Janice API key — every submission
calls the Janice appraisal API synchronously.

1. Request a developer API key from Janice (https://janice.e-351.com).
2. Set it in `.env`:
   ```
   JANICE_API_KEY=your-key-here
   ```
3. Restart the `web` service so it picks up the new value:
   ```bash
   docker compose up -d
   ```

`.env` is gitignored (see `.gitignore`) and must **never** be committed —
it also holds `DJANGO_SECRET_KEY` and the Postgres password. `.env.example`
is the committed template; copy it, don't edit it in place.

## 3. Production

Production uses the same image as development, run under Gunicorn instead
of `runserver`, with the source bind-mount removed so the container runs
exactly what was baked into the image at build time. `docker-compose.yml`
itself is unchanged for this — `docker-compose.prod.yml` is an override
layered on top:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py migrate
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py seed_catalog
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

Static files (including django-unfold's admin CSS/JS) are collected into
the image automatically during `docker build` (`RUN python manage.py
collectstatic --noinput` in the `Dockerfile`) and served by WhiteNoise. With
`DEBUG=0`, Django no longer serves static files itself, so if this step is
ever skipped the admin renders unstyled — collectstatic having already run
at build time means there's nothing to remember to do here.

### Checklist: settings that MUST change before going live

All of these are set via `.env`, read by `config/settings.py`. The
defaults are safe for local development only.

| Setting | Change to |
|---|---|
| `DJANGO_SECRET_KEY` | A real, random secret. Generate one, e.g. `python -c "import secrets; print(secrets.token_urlsafe(50))"`. Never ship the `insecure-dev-key` default. |
| `DJANGO_DEBUG` | `0`. (Already set by `docker-compose.prod.yml`, but double-check `.env` too — the override only affects the `web` container's environment, not any other process reading `.env`.) |
| `DJANGO_ALLOWED_HOSTS` | The real hostname(s) the app is served on, comma-separated. `localhost,127.0.0.1` will reject every real request. |
| `POSTGRES_PASSWORD` | A strong, unique password. The `buyback` default is a dev convenience, not a credential. |

## 4. Known limitations to address when scaling

These were identified in code review and deliberately left as documentation
rather than fixed now, either because they don't matter at the current
scale (a single Gunicorn worker, no reverse proxy) or because fixing them
is a deployment-topology decision, not a code change.

- **Rate limiting uses `LocMemCache`.** Counters live in the process memory
  of a single Gunicorn worker. With more than one worker, each worker has
  its own counter, so the effective site-wide limit is `BUYBACK_RATE_LIMIT
  × worker count`, not `BUYBACK_RATE_LIMIT`. Before running with more than
  one worker, switch `CACHES["default"]` in `config/settings.py` to a
  shared backend, e.g. `django.core.cache.backends.redis.RedisCache`
  pointed at a Redis instance.

- **Rate limiting keys on `REMOTE_ADDR`.** Behind a reverse proxy or CDN,
  every request's `REMOTE_ADDR` is the proxy's own IP, not the visitor's —
  this collapses the per-IP limit into a single global bucket shared by
  every visitor. If you deploy behind a proxy, configure `django_ratelimit`
  to key on the forwarded client IP instead, and make sure the proxy is
  actually setting `X-Forwarded-For` (and that Django trusts only that
  proxy for it). This matters more than it sounds: the Janice API quota is
  tied to a single, personally-issued key, so a collapsed rate limit is a
  quota-exhaustion risk, not just an abuse risk.

- **No HTTPS-related settings are configured.** Behind HTTPS (which any
  real deployment should be), set in `config/settings.py` (or via env vars
  it reads): `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE=True`,
  `CSRF_COOKIE_SECURE=True`, `SECURE_SSL_REDIRECT=True`, and
  `CSRF_TRUSTED_ORIGINS`. None of these are safe defaults for a plain-HTTP
  local setup, which is why they aren't set already.

- **Paste size is bounded only by Django's default
  `DATA_UPLOAD_MAX_MEMORY_SIZE`** (2.5 MB). An oversized paste raises
  `RequestDataTooBig`, which with `DEBUG=0` is a plain 400 — acceptable,
  but not a friendly error page. Set an explicit, smaller limit in
  `config/settings.py` if you want a nicer message for this case.

- **The Janice field mapping was verified against the published OpenAPI
  schema, not a live response** — no API key was available during
  development. Confirm it against a real appraisal on first use in
  production. The mapping is entirely confined to
  `JaniceAppraisalGateway._to_result` in
  `buyback/infrastructure/janice.py`, so any correction is a one-line fix
  localized to that method.

## 5. Re-running `seed_catalog`

CCP periodically publishes new items. `seed_catalog` is idempotent — it
upserts by ID (`update_conflicts=True` on categories, groups, and types),
so re-running it is always safe and never duplicates data:

```bash
docker compose exec web python manage.py seed_catalog
```

(Use the `-f docker-compose.yml -f docker-compose.prod.yml` form in
production, as in §3.)

## ESI contract checking (optional)

1. Register an application at <https://developers.eveonline.com/applications>.
   - Scope: `esi-characters.read_contacts.v1`. It must be **ticked on
     the application itself**, not just requested by the app. If it is missing,
     SSO answers `The requested '<scope>' scope is not valid` at login — an
     application-registration problem, not a wrong scope string. Note it is
     `esi-characters.read_contacts.v1`, not
     `esi-characters.read_contacts.v1`, which is the address book.
   - Callback URL: `https://your-domain/admin/contracts/callback/` — this must
     match `ESI_CALLBACK_URL` exactly, or SSO rejects the login with
     `invalid_request: redirect_uri mismatch`.
2. Generate the token encryption key:
   `docker compose exec web python manage.py generate_esi_key`
3. Set `ESI_CLIENT_ID`, `ESI_CLIENT_SECRET`, `ESI_CALLBACK_URL`, `ESI_TOKEN_KEY`
   and optionally `ESI_USER_AGENT`.
4. Restart, then connect your character at **Contracts → Contract check**.

Keep `ESI_TOKEN_KEY` with your other secrets. Losing it does not lose data — the
stored refresh token simply becomes unreadable and the page asks you to log in
again.
