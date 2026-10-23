"""
Django settings for config project.
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# BASE_DIR is /backend (this file is /backend/config/settings.py). The .env lives at the
# repo root so Docker Compose and Django read the same file — see docs/setup.md.
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
load_dotenv(REPO_ROOT / ".env")


def env_list(name: str, default: str = "") -> list[str]:
    """A comma-separated environment variable as a list, ignoring blanks and spaces."""
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# TM05-113: production fails closed. DEBUG is off unless .env turns it on, and with DEBUG off
# a missing SECRET_KEY stops Django rather than silently using the dev key. Development
# (DEBUG=True, which .env.example sets) keeps the dev fallback.
DEBUG = os.environ.get("DEBUG", "False") == "True"
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "SECRET_KEY is not set. Production needs a long random value; for development, "
            "set DEBUG=True in .env (see .env.example)."
        )
    SECRET_KEY = "django-insecure-dev-only-change-me"
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# Render sets this to the service's own onrender.com hostname.
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "accounts",
    "health",
    "api",
    "geodata",
    "pipeline",
    "devdata",
    "scoring",
    "analysis",
    "enrichment",
    "planning",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the admin's collected static files from gunicorn itself (TM05-113). Must sit
    # directly below SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # GeoJSON is highly compressible repeated numeric text: a full-park water response
    # measures 447 kB raw and 72 kB gzipped, a 6.2x reduction. Must sit above
    # CommonMiddleware so it wraps the rendered response.
    "django.middleware.gzip.GZipMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
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
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ImproperlyConfigured(
        "DATABASE_URL is not set. Copy .env.example to .env at the repo root and fill it "
        "in, then start the database with `docker compose up -d` (see docs/setup.md)."
    )

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        engine="django.contrib.gis.db.backends.postgis",
    )
}

# Django 5.1 locates GDAL by probing names for versions 3.0-3.8 only, so a newer Homebrew
# GDAL is never found and django.contrib.gis fails to import. Both are set in .env.example;
# when unset these stay None, which Django treats as "search the default paths" (Linux).
GDAL_LIBRARY_PATH = os.environ.get("GDAL_LIBRARY_PATH")
GEOS_LIBRARY_PATH = os.environ.get("GEOS_LIBRARY_PATH")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Compressed but not manifest storage: the manifest variant errors on any template that
# renders before collectstatic has run, which includes the test suite.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

# TM05-88: login and register are rate-limited per client IP (accounts/throttling.py,
# docs/auth.md). Only those two views throttle; nothing else is affected.
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_RATES": {
        "auth-login": os.environ.get("AUTH_LOGIN_RATE", "10/min"),
        "auth-register": os.environ.get("AUTH_REGISTER_RATE", "10/hour"),
    },
    # The client is REMOTE_ADDR alone. DRF's default (None) trusts the whole
    # X-Forwarded-For header, which a client writes itself: a new value per request would
    # never be limited. Behind a reverse proxy, set this to the number of proxies.
    "NUM_PROXIES": int(os.environ.get("THROTTLE_NUM_PROXIES", "0")),
    "EXCEPTION_HANDLER": "accounts.throttling.exception_handler",
}

# TM05-103: `make dev-phone` serves the frontend over HTTPS on the LAN so a phone can test
# geolocation. In development only (DEBUG on), trust that one origin for CORS and CSRF. It
# is ignored when DEBUG is off, so it can never widen a production deployment.
DEV_LAN_ORIGIN = os.environ.get("DEV_LAN_ORIGIN", "").strip()
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if DEBUG and DEV_LAN_ORIGIN:
    CORS_ALLOWED_ORIGINS.append(DEV_LAN_ORIGIN)
    CSRF_TRUSTED_ORIGINS.append(DEV_LAN_ORIGIN)

# TM05-113: HTTPS behind a TLS-terminating proxy (Render). The proxy sets
# X-Forwarded-Proto, which Django trusts only when this is on. Each is opt-in through the
# environment, so local development and the test suite (plain HTTP) are unaffected.
if os.environ.get("BEHIND_TLS_PROXY") == "True":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    # The platform's health check calls the container over plain HTTP.
    SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))

# GEOS logs a warning for every ring it finds invalid while reading source geometry.
# Real data produces these in bulk -- one small PAD-US bounding box emitted 149 lines,
# and NHD will emit thousands -- which buries anything worth reading. Raising this logger
# to ERROR keeps genuine failures visible while dropping the per-ring notices. The
# framework still records every skipped record in IngestRun.notes, so nothing is lost.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.contrib.gis": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
