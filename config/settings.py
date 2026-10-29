"""
Einstellungen der Protokolldatenbank.

Alle betriebsrelevanten Werte kommen aus Umgebungsvariablen bzw. einer
``.env``-Datei im Projektverzeichnis (siehe ``.env.example``). Alles, was
im Alltag geändert werden soll (Preise, Stripe, E-Mail, Texte …), wird im
Adminbereich der Webseite gepflegt und in der Datenbank gespeichert.
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(BASE_DIR / ".env")


def env(name, default=""):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


def env_list(name):
    return [item.strip() for item in env(name).split(",") if item.strip()]


TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"

DEBUG = env_bool("DEBUG", False)
SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "unsicherer-entwicklungsschluessel-nicht-im-betrieb-verwenden"
    else:
        raise RuntimeError("SECRET_KEY ist nicht gesetzt (siehe .env.example).")

SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")
_site = urlparse(SITE_URL)
ALLOWED_HOSTS = list({_site.hostname or "localhost", "localhost", "127.0.0.1", *env_list("ALLOWED_HOSTS")})
CSRF_TRUSTED_ORIGINS = [f"{_site.scheme}://{_site.netloc}"] + [
    origin for origin in env_list("CSRF_TRUSTED_ORIGINS")
]

if TESTING:
    import tempfile

    DATA_DIR = Path(tempfile.mkdtemp(prefix="protokolle-test-"))
else:
    DATA_DIR = Path(env("DATA_DIR", str(BASE_DIR / "data"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "accounts",
    "protocols",
    "payments",
    "verwaltung",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
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
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if env("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER"),
            "PASSWORD": env("POSTGRES_PASSWORD"),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "db.sqlite3",
            "OPTIONS": {
                "timeout": 20,
                "transaction_mode": "IMMEDIATE",
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            },
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Gültigkeit von Bestätigungs- und Passwort-Links (in Sekunden)
PASSWORD_RESET_TIMEOUT = 3 * 24 * 60 * 60

LANGUAGE_CODE = "de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Hochgeladene Protokolle liegen außerhalb des öffentlich erreichbaren Bereichs
# und werden ausschließlich über geprüfte Download-Ansichten ausgeliefert.
MEDIA_ROOT = DATA_DIR / "uploads"
PROTOCOL_FILES_ROOT = MEDIA_ROOT / "protokolle"
FILE_UPLOAD_PERMISSIONS = 0o640
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "protokolle@localhost")

# Geheimnisse dürfen alternativ als Umgebungsvariable gesetzt werden
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET")
SMTP_PASSWORD = env("SMTP_PASSWORD")

X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
if _site.scheme == "https" and not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
BEHIND_PROXY = env_bool("BEHIND_PROXY", False)
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
if env_bool("SECURE_SSL_REDIRECT", False):
    SECURE_SSL_REDIRECT = True
# Optional: HTTP Strict Transport Security (nur setzen, wenn die Seite dauerhaft nur per HTTPS läuft)
SECURE_HSTS_SECONDS = int(env("HSTS_SECONDS", "0") or 0)
# SAMEORIGIN ist nötig, damit PDFs in der Protokollansicht eingebettet angezeigt werden können.
SILENCED_SYSTEM_CHECKS = ["security.W019"]

# Dateibasierter Cache: wird von allen Gunicorn-Prozessen geteilt (wichtig für die Login-Sperre).
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
        if TESTING
        else {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache", "LOCATION": str(DATA_DIR / "cache")}
    )
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}

if TESTING:
    import warnings

    warnings.filterwarnings("ignore", message="No directory at", module="django.core.handlers.base")
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    LOGGING["root"]["level"] = "CRITICAL"
    LOGGING["loggers"]["django"]["level"] = "CRITICAL"
