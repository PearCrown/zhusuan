"""Explicit cloud profile. Never use the development web server for deployment."""
from urllib.parse import urlsplit
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from .settings import *  # noqa: F403

if DEBUG:
    raise ImproperlyConfigured("生产配置要求DJANGO_DEBUG=false。")
site_origin = required("PRODUCTION_SITE_ORIGIN")
try:
    URLValidator(schemes=["https"])(site_origin)
    parsed_origin = urlsplit(site_origin)
    parsed_origin.port
except (ValueError, ValidationError):
    raise ImproperlyConfigured("生产站点来源格式无效。") from None
if (parsed_origin.scheme != "https" or not parsed_origin.hostname or parsed_origin.username or parsed_origin.password
        or parsed_origin.path or parsed_origin.query or parsed_origin.fragment or not site_origin.isascii()):
    raise ImproperlyConfigured("PRODUCTION_SITE_ORIGIN必须为无路径的HTTPS站点来源。")
if parsed_origin.hostname not in ALLOWED_HOSTS or any("*" in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("生产主机白名单必须包含站点主机，不能包含通配符。")
CSRF_TRUSTED_ORIGINS = [site_origin]
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = positive_integer("PRODUCTION_HSTS_SECONDS", 3600, 31536000)
# Domain ownership must be reviewed before extending HSTS to subdomains/preload.
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# Enable only with a private trusted proxy that overwrites forwarded headers.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if boolean("TRUST_HTTPS_PROXY") else None
USE_X_FORWARDED_HOST = False
ca_path = Path(required("DB_SSLROOTCERT"))
if not ca_path.is_absolute() or not ca_path.is_file():
    raise ImproperlyConfigured("DB_SSLROOTCERT必须为存在的绝对CA证书文件路径。")
DATABASES = {"default": {**DATABASES["default"], "OPTIONS": {**DATABASES["default"]["OPTIONS"], "sslmode": "verify-full", "sslrootcert": str(ca_path)},
    "CONN_MAX_AGE": positive_integer("DB_CONN_MAX_AGE", 60, 600), "CONN_HEALTH_CHECKS": True}}
