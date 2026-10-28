from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from core.test_runner import IsolatedTestRunner


class TestDatabaseSafetyTests(SimpleTestCase):
    @override_settings(ISOLATED_TEST_DATABASE=False)
    def test_development_configuration_is_rejected_before_database_setup(self):
        with self.assertRaises(ImproperlyConfigured):
            IsolatedTestRunner(keepdb=True)

    def test_test_database_name_cannot_point_elsewhere(self):
        with patch.dict(settings.DATABASES["default"]["TEST"], {"NAME": "huaxia_accounts"}):
            with self.assertRaises(ImproperlyConfigured):
                IsolatedTestRunner(keepdb=True)
