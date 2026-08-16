import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

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
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
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
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Janice integration
JANICE_API_KEY = os.environ.get("JANICE_API_KEY", "")
JANICE_BASE_URL = os.environ.get("JANICE_BASE_URL", "https://janice.e-351.com/api/rest/v2")

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
        ],
    },
    "COLORS": {
        "primary": {
            "50": "245 247 250",
            "100": "231 237 243",
            "200": "208 218 231",
            "300": "174 192 213",
            "400": "141 165 196",
            "500": "114 144 182",
            "600": "93 129 172",
            "700": "75 106 145",
            "800": "59 84 114",
            "900": "47 67 91",
            "950": "31 44 61",
        },
    },
}
