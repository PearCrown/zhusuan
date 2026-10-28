import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.test import TestCase, SimpleTestCase
from django.db import DatabaseError


class ReadinessTests(TestCase):
    def test_database_ready_no_store_and_head(self):
        response=self.client.get("/health/ready/")
        self.assertEqual(response.status_code,200);self.assertEqual(response.json(),{"status":"ok"})
        self.assertIn("no-store",response["Cache-Control"])
        self.assertEqual(self.client.head("/health/ready/").content,b"")
        self.assertEqual(self.client.post("/health/ready/").status_code,405)

    def test_failure_does_not_expose_database_info_or_break_liveness(self):
        with patch("django.db.connection.cursor",side_effect=DatabaseError("password=private")):
            response=self.client.get("/health/ready/")
            self.assertEqual(response.status_code,503);self.assertEqual(response.json(),{"status":"unavailable"})
            self.assertNotIn("private",response.content.decode())
            self.assertEqual(self.client.get("/health/live/").status_code,200)


class ProductionConfigTests(SimpleTestCase):
    def inspect(self, deploy=False, **changes):
        with TemporaryDirectory() as folder:
            ca=Path(folder)/"ca.pem";ca.write_text("configuration-test-only")
            env={**os.environ,"DJANGO_DEBUG":"false","DJANGO_SECRET_KEY":"test-only-cloud-config-"*4,"DJANGO_ALLOWED_HOSTS":"platform.example.org", "PRODUCTION_SITE_ORIGIN":"https://platform.example.org","DB_SSLROOTCERT":str(ca),"CONTACT_MESSAGE_BACKEND":"disabled","TRUST_HTTPS_PROXY":"false",**changes}
            code="import config.production as p; import json; print(json.dumps([p.DEBUG,p.SECURE_SSL_REDIRECT,p.SESSION_COOKIE_SECURE,p.CSRF_TRUSTED_ORIGINS,p.DATABASES['default']['OPTIONS']['sslmode'],p.SECURE_PROXY_SSL_HEADER]))"
            if deploy:
                code="from django.core.management import execute_from_command_line; execute_from_command_line(['manage.py','check','--deploy','--fail-level','ERROR','--settings=config.production'])"
            return subprocess.run([sys.executable,"-X","utf8","-c",code],env=env,capture_output=True,text=True,timeout=15)

    def test_safe_configuration_and_explicit_proxy_trust(self):
        result=self.inspect();self.assertEqual(result.returncode,0)
        self.assertEqual(json.loads(result.stdout),[False,True,True,["https://platform.example.org"],"verify-full",None])
        result=self.inspect(TRUST_HTTPS_PROXY="true")
        self.assertEqual(json.loads(result.stdout)[-1],["HTTP_X_FORWARDED_PROTO","https"])

    def test_unsafe_or_incomplete_configuration_fails(self):
        for changes in [{"DJANGO_DEBUG":"true"},{"DB_SSLROOTCERT":""},{"DB_SSLROOTCERT":"relative.pem"},{"CONTACT_MESSAGE_BACKEND":"memory"},{"PRODUCTION_SITE_ORIGIN":"http://platform.example.org"},{"PRODUCTION_SITE_ORIGIN":"https://evil.example.org"},{"PRODUCTION_SITE_ORIGIN":"https://platform.example.org:bad"},{"PRODUCTION_SITE_ORIGIN":"https://platform.example.org/path"},{"TRUST_HTTPS_PROXY":"yes"}]:
            with self.subTest(changes=changes):self.assertNotEqual(self.inspect(**changes).returncode,0)

    def test_production_framework_deployment_checks_have_no_errors(self):
        result=self.inspect(deploy=True)
        self.assertEqual(result.returncode,0,result.stderr)
        # HSTS subdomain/preload policy is intentionally not asserted for unknown domains.
        self.assertNotIn("security.W008",result.stderr)
        self.assertNotIn("security.W012",result.stderr)
        self.assertNotIn("security.W018",result.stderr)
