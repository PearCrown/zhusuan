"""Shared project configuration. Production deployment is a later task."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"缺少必要配置 {name}；请按 .env.example 配置 .env。")
    return value


def boolean(name, default="false"):
    value = os.environ.get(name, default).strip().lower()
    if value not in {"true", "false"}:
        raise ImproperlyConfigured(f"{name} 必须为 true 或 false。")
    return value == "true"


def positive_integer(name, default, maximum):
    try:
        value = int(os.environ.get(name, str(default)))
        if not 1 <= value <= maximum:
            raise ValueError
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} 必须为1至{maximum}之间的整数。") from exc
    return value


SECRET_KEY = required("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY 至少需要50个随机字符。")
DEBUG = boolean("DJANGO_DEBUG")
ALLOWED_HOSTS = [host.strip() for host in required("DJANGO_ALLOWED_HOSTS").split(",") if host.strip()]
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS 必须列出具体主机，不能使用 *。")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "accounts",
    "classrooms",
    "gameplay",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.ApiSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.JsonRequestGuardMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

try:
    database_port = int(required("DB_PORT"))
    if not 1 <= database_port <= 65535:
        raise ValueError
except ValueError as exc:
    raise ImproperlyConfigured("DB_PORT 必须为1至65535之间的整数。") from exc

DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": required("DB_NAME"),
    "USER": required("DB_USER"),
    "PASSWORD": required("DB_PASSWORD"),
    "HOST": required("DB_HOST"),
    "PORT": database_port,
    "OPTIONS": {"connect_timeout": 5},
    "CONN_MAX_AGE": 0,
}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator", "OPTIONS": {"user_attributes": ["username", "display_name", "first_name", "last_name", "email"]}},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
# Apply the fail-closed test runner even when the CLI is invoked outside manage.py.
TEST_RUNNER = "core.test_runner.IsolatedTestRunner"
CSRF_FAILURE_VIEW = "core.api.csrf_failure"
REGISTER_RATE_LIMIT_MAX_ATTEMPTS = positive_integer("REGISTER_RATE_LIMIT_MAX_ATTEMPTS", 120, 10000)
REGISTER_RATE_LIMIT_WINDOW_SECONDS = positive_integer("REGISTER_RATE_LIMIT_WINDOW_SECONDS", 600, 86400)
LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS = positive_integer("LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS", 300, 10000)
LOGIN_ACCOUNT_IP_RATE_LIMIT_MAX_ATTEMPTS = positive_integer("LOGIN_ACCOUNT_IP_RATE_LIMIT_MAX_ATTEMPTS", 10, 1000)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = positive_integer("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 600, 86400)
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = positive_integer("SESSION_AGE_SECONDS", 28800, 604800)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = False
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
