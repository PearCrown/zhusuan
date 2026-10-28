"""Only use a separately provisioned test database and restricted test role."""

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

load_dotenv(BASE_DIR / ".env.test", override=False)
test_name = required("TEST_DB_NAME")
test_user = required("TEST_DB_USER")
if not test_name.startswith("test_huaxia_") or test_name == DATABASES["default"]["NAME"]:
    raise ImproperlyConfigured("测试数据库必须为独立的test_huaxia_前缀数据库。")
if test_user == DATABASES["default"]["USER"]:
    raise ImproperlyConfigured("测试数据库必须使用独立测试账号。")
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": test_name,
    "USER": test_user,
    "PASSWORD": required("TEST_DB_PASSWORD"),
    "HOST": required("TEST_DB_HOST"),
    "PORT": required("TEST_DB_PORT"),
    "OPTIONS": {"connect_timeout": 5},
    "CONN_MAX_AGE": 0,
    "TEST": {"NAME": test_name},
}}
TEST_RUNNER = "core.test_runner.IsolatedTestRunner"
ISOLATED_TEST_DATABASE = True
