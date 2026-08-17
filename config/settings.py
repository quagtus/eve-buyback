import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"


def _csv_env(name, default=""):
    """Split a comma-separated env var, dropping blanks and stray whitespace."""
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


ALLOWED_HOSTS = _csv_env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# Django 4+ requires the SCHEME here, not a bare hostname: "https://buyback.example.com",
# not "buyback.example.com". A bare hostname raises ImproperlyConfigured at startup,
# and omitting the origin entirely is what produces "CSRF verification failed —
# Origin checking failed" on a POST from a deployed domain.
CSRF_TRUSTED_ORIGINS = _csv_env("DJANGO_CSRF_TRUSTED_ORIGINS")

# Behind a reverse proxy terminating TLS, Django sees http:// on the inbound
# request and will reject an https:// Origin as a mismatch. This tells it to
# trust the proxy's forwarded scheme.
#
# Only enable it when a proxy is genuinely in front: if the app is reachable
# directly, a client can forge this header and Django would believe an
# unencrypted request was secure.
if os.environ.get("DJANGO_BEHIND_TLS_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Cookie flags follow the same switch: marking cookies Secure over plain HTTP
# makes them undeliverable, which would lock you out of the admin in dev.
_HTTPS = os.environ.get("DJANGO_SECURE_COOKIES", "0") == "1"
SESSION_COOKIE_SECURE = _HTTPS
CSRF_COOKIE_SECURE = _HTTPS

INSTALLED_APPS = [
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "catalog",
    "pricing",
    "buyback",
    "siteconfig",
    "contracts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "config.middleware.AdminEnglishMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                # Supplies LANGUAGES and LANGUAGE_CODE to templates. Without it
                # base.html's `{% if LANGUAGES|length > 1 %}` is always false, so
                # the language switcher never renders no matter how many locales
                # are configured, and <html lang> is stuck on "en".
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                'siteconfig.context_processors.site_config',
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "buyback"),
        "USER": os.environ.get("POSTGRES_USER", "buyback"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "buyback"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Only English ships today. Adding a locale is a directory under locale/
# plus a translation pass — no code change required.
LANGUAGES = [
    ("en", "English"),
]

LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Tailwind compiles to static/css/app.css, which is neither an app's static/
# directory nor inside STATIC_ROOT, so Django cannot see it without this.
# Without it {% static 'css/app.css' %} resolves to a URL that 404s and
# collectstatic silently omits the file — the whole site renders unstyled
# while every test still passes, because tests assert on HTML, not CSS.
STATICFILES_DIRS = [BASE_DIR / "static"]

# Admin-uploaded files (currently just the site logo).
#
# MEDIA_ROOT was previously unset, so upload_to resolved against the working
# directory and uploads landed loose in the source tree — which is how a 2.4 MB
# wallpaper ended up committed. Everything under static/uploads/ is gitignored.
#
# The URL is /uploads/, deliberately NOT /static/uploads/: Django refuses to
# start when MEDIA_URL sits inside STATIC_URL ("runserver can't serve media if
# MEDIA_URL is within STATIC_URL"). Only the on-disk location is under static/.
MEDIA_ROOT = BASE_DIR / "static" / "uploads"
MEDIA_URL = "/uploads/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Janice integration
JANICE_API_KEY = os.environ.get("JANICE_API_KEY", "")
JANICE_BASE_URL = os.environ.get("JANICE_BASE_URL", "https://janice.e-351.com/api/rest/v2")

# EVE SSO / ESI integration for the admin contract check.
#
# Client id and secret are environment variables for the same reason
# JANICE_API_KEY is: credentials stay out of the database and its backups.
# The refresh token cannot be — it is obtained at runtime — so it is encrypted
# with ESI_TOKEN_KEY before it is stored. Generate that key with
# `manage.py generate_esi_key`.
ESI_CLIENT_ID = os.environ.get("ESI_CLIENT_ID", "")
ESI_CLIENT_SECRET = os.environ.get("ESI_CLIENT_SECRET", "")
ESI_TOKEN_KEY = os.environ.get("ESI_TOKEN_KEY", "")

# Explicit rather than derived from the request: this must match the callback
# registered at developers.eveonline.com byte for byte, and building it from
# build_absolute_uri() behind a TLS-terminating proxy is the usual cause of
# "invalid_request: redirect_uri mismatch".
ESI_CALLBACK_URL = os.environ.get("ESI_CALLBACK_URL", "")

# CCP asks third-party applications to identify themselves with a contactable
# string on every ESI call.
ESI_USER_AGENT = os.environ.get("ESI_USER_AGENT", "eve-buyback")

# Space-separated scopes requested at login. Must match the scopes ticked on
# your application at developers.eveonline.com, or SSO rejects the login with
# "The requested '<scope>' scope is not valid".
#
# If a check then comes back 401, ESI states which scope it wanted in the
# response body and the page shows that text verbatim — change this to match it.
ESI_SCOPES = os.environ.get("ESI_SCOPES", "esi-contracts.read_character_contracts.v1")

# ESI requires an X-Compatibility-Date header on every request. It pins which
# revision of the API answers, so CCP can change response shapes without
# breaking existing callers.
#
# Pinned on purpose rather than tracking the newest date: an automatic bump is
# precisely the silent breakage this header exists to prevent. Accepted values
# are listed at https://esi.evetech.net/meta/compatibility-dates — before moving
# it forward, re-read the spec for the contracts and universe/names endpoints.
ESI_COMPATIBILITY_DATE = os.environ.get("ESI_COMPATIBILITY_DATE", "2026-08-04")

# Public quote submission rate limit (see Task 17)
BUYBACK_RATE_LIMIT = os.environ.get("BUYBACK_RATE_LIMIT", "10/h")

# django-ratelimit needs a real cache backend to count requests against.
# LocMemCache is per-process: counters are not shared across Gunicorn
# workers, so the effective limit is "N per worker", not "N site-wide".
# That is acceptable for a single-worker deployment; it is pinned here
# explicitly (rather than left to Django's implicit default) so the
# limitation is documented, not accidental. Move to a shared cache (e.g.
# Redis) if this ever runs with more than one worker process.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "buyback-ratelimit",
    }
}

RATELIMIT_ENABLE = os.environ.get("RATELIMIT_ENABLE", "1") == "1"

UNFOLD = {
    "SITE_TITLE": "EVE Buyback Admin",
    "SITE_HEADER": "EVE Buyback",
    "SIDEBAR": {
        "show_search": True,
        "navigation": [
            {
                "title": "Pricing",
                "items": [
                    {"title": "Category defaults",
                     "link": "/admin/pricing/categorydefaultpercent/"},
                    {"title": "Custom rules", "link": "/admin/pricing/customrule/"},
                    {"title": "Sales", "link": "/admin/pricing/salerule/"},
                    {"title": "Blacklist", "link": "/admin/pricing/blacklistentry/"},
                    {"title": "Reprocessing", "link": "/admin/pricing/reprocessingrule/"},
                    {"title": "Rule summary", "link": "/admin/pricing/summary/"},
                ],
            },
            {
                "title": "Buyback",
                "items": [
                    {"title": "Quotes", "link": "/admin/buyback/quote/"},
                    {"title": "Settings", "link": "/admin/siteconfig/siteconfig/"},
                ],
            },
            {
                "title": "Contracts",
                "items": [
                    {"title": "Contract check", "link": "/admin/contracts/check/"},
                ],
            },
        ],
    },
    "COLORS": {
        # EVE amber, anchored so white-on-primary-600 stays legible (6.51).
        # The site's own accent #fca311 would give 2.02 here — Unfold paints
        # white text on this fill, so the admin scale runs darker than the
        # public site's accent on purpose.
        "primary": {
            "50": "255 249 240",
            "100": "255 240 219",
            "200": "255 223 178",
            "300": "255 199 122",
            "400": "255 169 51",
            "500": "224 130 0",
            "600": "138 80 0",
            "700": "112 65 0",
            "800": "92 53 0",
            "900": "71 41 0",
            "950": "46 27 0",
        },
    },
}
