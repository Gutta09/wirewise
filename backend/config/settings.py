"""Django settings for Wirewise."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Read a KEY=value file into the environment, without adding a dependency.

    Values already set in the real environment win, so a deploy's own variables
    are never overwritten by a stray .env file.
    """
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    """Read an environment variable, treating a blank value as unset.

    ``.env.example`` ships keys with empty values as documentation, so an empty
    string has to fall back to the default rather than override it.
    """
    raw = os.environ.get(name)
    return raw.strip() if raw and raw.strip() else default


def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name)
    return raw.lower() in {"1", "true", "yes", "on"} if raw else default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,.onrender.com")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "reconciliation",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "reconciliation.api.exceptions.exception_handler",
}

# There is no login, so the React dev server talks to the API cross-origin.
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)
CORS_ALLOW_HEADERS = ("accept", "content-type", "x-organization", "x-requested-with")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

# Maximum accepted size of an uploaded bank statement, in bytes.
IMPORT_MAX_UPLOAD_BYTES = int(env("IMPORT_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

# Optional Airtable sync for needs_review transactions (Section 10 bonus).
AIRTABLE_ENABLED = env_bool("AIRTABLE_ENABLED", False)
AIRTABLE_API_TOKEN = env("AIRTABLE_API_TOKEN")
AIRTABLE_BASE_ID = env("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = env("AIRTABLE_TABLE_NAME", "Needs Review")
AIRTABLE_TIMEOUT_SECONDS = float(env("AIRTABLE_TIMEOUT_SECONDS", "5"))
