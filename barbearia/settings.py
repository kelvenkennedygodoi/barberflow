import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(nome, padrao=False):
    return os.getenv(nome, str(padrao)).lower() in {"1", "true", "sim", "yes", "on"}


DEBUG = env_bool("DEBUG", True)
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-inseguro-troque-antes-de-publicar"
    else:
        raise RuntimeError("Defina SECRET_KEY antes de iniciar o sistema em produção.")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "gestao",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "gestao.middleware.AcessoAssinaturaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

USE_WHITENOISE = env_bool("USE_WHITENOISE", not DEBUG)
if USE_WHITENOISE:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "barbearia.urls"

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

WSGI_APPLICATION = "barbearia.wsgi.application"
ASGI_APPLICATION = "barbearia.asgi.application"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    banco = urlparse(DATABASE_URL)
    if banco.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("DATABASE_URL deve usar o protocolo postgres:// ou postgresql://.")
    parametros_banco = parse_qs(banco.query)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(banco.path.lstrip("/")),
            "USER": unquote(banco.username or ""),
            "PASSWORD": unquote(banco.password or ""),
            "HOST": banco.hostname or "localhost",
            "PORT": banco.port or 5432,
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
            "OPTIONS": {
                "sslmode": parametros_banco.get("sslmode", ["prefer"])[0],
            },
        }
    }
elif os.getenv("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "barberflow"),
            "USER": os.getenv("POSTGRES_USER", "barberflow"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": int(os.getenv("POSTGRES_PORT", "5432")),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
            "OPTIONS": {"sslmode": os.getenv("DB_SSLMODE", "prefer")},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
if USE_WHITENOISE:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "gestao.Usuario"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

CSRF_TRUSTED_ORIGINS = [
    origem.strip()
    for origem in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origem.strip()
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0" if DEBUG else "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {
        "handlers": ["console"],
        "level": os.getenv("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": os.getenv("DJANGO_REQUEST_LOG_LEVEL", "ERROR"),
            "propagate": False,
        }
    },
}

# Regras iniciais do autoagendamento. Depois poderão ser configuradas por barbearia.
PUBLIC_BOOKING_SLOT_MINUTES = 15
PUBLIC_BOOKING_LEAD_MINUTES = 30
PUBLIC_BOOKING_MAX_DAYS = 60

# Integração com a API oficial do WhatsApp Business (Meta Cloud API).
WHATSAPP_ENABLED = env_bool("WHATSAPP_ENABLED", False)
WHATSAPP_DRY_RUN = env_bool("WHATSAPP_DRY_RUN", DEBUG)
WHATSAPP_API_BASE_URL = os.getenv(
    "WHATSAPP_API_BASE_URL", "https://graph.facebook.com"
).rstrip("/")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_LANGUAGE_CODE = os.getenv("WHATSAPP_LANGUAGE_CODE", "pt_BR")
WHATSAPP_TEMPLATE_CONFIRMACAO = os.getenv("WHATSAPP_TEMPLATE_CONFIRMACAO", "")
WHATSAPP_TEMPLATE_LEMBRETE = os.getenv("WHATSAPP_TEMPLATE_LEMBRETE", "")
WHATSAPP_REMINDER_HOURS = tuple(
    int(valor.strip())
    for valor in os.getenv("WHATSAPP_REMINDER_HOURS", "24,2").split(",")
    if valor.strip()
)
WHATSAPP_TIMEOUT_SECONDS = int(os.getenv("WHATSAPP_TIMEOUT_SECONDS", "15"))
WHATSAPP_MAX_RETRIES = int(os.getenv("WHATSAPP_MAX_RETRIES", "3"))
