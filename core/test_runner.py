from django.core.exceptions import ImproperlyConfigured
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.test.runner import DiscoverRunner


class IsolatedTestRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        if not getattr(settings, "ISOLATED_TEST_DATABASE", False):
            raise ImproperlyConfigured("拒绝使用开发配置运行测试；请运行scripts/test.ps1。")
        if not kwargs.get("keepdb") or kwargs.get("parallel", 0) not in {0, 1}:
            raise ImproperlyConfigured("测试须使用--keepdb且不能并行克隆数据库；请运行scripts/test.ps1。")
        if not settings.DATABASES["default"]["NAME"].startswith("test_huaxia_"):
            raise ImproperlyConfigured("拒绝使用非专用测试数据库。")
        if settings.DATABASES["default"].get("TEST", {}).get("NAME") != settings.DATABASES["default"]["NAME"]:
            raise ImproperlyConfigured("测试目标数据库与专用连接不一致，拒绝继续。")
        super().__init__(*args, **kwargs)

    def setup_databases(self, **kwargs):
        configuration = super().setup_databases(**kwargs)
        database = connections["default"].settings_dict
        expected = settings.DATABASES["default"]["TEST"]["NAME"]
        if database["NAME"] != expected or not expected.startswith("test_huaxia_"):
            raise ImproperlyConfigured("拒绝清理未确认的数据库。")
        # --keepdb retains schema and may retain rows from manual HTTP checks or
        # an interrupted run. Clear only the verified disposable test database.
        call_command("flush", database="default", interactive=False, verbosity=0)
        return configuration
