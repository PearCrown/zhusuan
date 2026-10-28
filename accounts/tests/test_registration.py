from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import RateLimitBucket
from accounts.rate_limits import registration_limit
from accounts.roles import STUDENT
from classrooms.models import StudentEnrollment

User = get_user_model()


class RegistrationTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.client = Client(enforce_csrf_checks=True)
        response = self.client.get("/auth/csrf")
        self.assertEqual(response.status_code, 200)
        self.token = response.json()["data"]["csrfToken"]
        self.payload = {"username": "student01", "displayName": "小明", "password": "Bamboo!River-7429-Cloud"}

    def post(self, payload=None, **extra):
        return self.client.post(
            "/auth/register", data=self.payload if payload is None else payload,
            content_type="application/json", HTTP_X_CSRFTOKEN=self.token, **extra,
        )

    def test_success_only_creates_student_without_session_or_class(self):
        payload = {**self.payload, "username": "  Ｓtudent01 ", "displayName": " 小明 "}
        response = self.post(payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        user = User.objects.get(pk=data["userId"])
        self.assertEqual(data, {"userId": str(user.pk), "username": "student01", "displayName": "小明", "role": "student"})
        self.assertEqual(list(user.groups.values_list("name", flat=True)), [STUDENT])
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.user_permissions.exists())
        self.assertFalse(StudentEnrollment.objects.filter(student=user).exists())
        self.assertTrue(user.check_password(payload["password"]))
        self.assertNotEqual(user.password, payload["password"])
        self.assertNotIn(payload["password"], response.content.decode())
        self.assertNotIn(user.password, response.content.decode())
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_password_is_not_trimmed_or_normalized(self):
        password = "  Bamboo!River-7429-Cloud  "
        response = self.post({**self.payload, "password": password})
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="student01")
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.check_password(password.strip()))

    def test_unknown_fields_cannot_set_role_class_or_identity(self):
        extra_fields = {
            "role": "teacher", "is_staff": True, "is_superuser": True,
            "groups": ["teacher"], "user_permissions": ["maintain_accounts"],
            "classId": "some-class", "userId": "some-user", "email": "test@example.invalid",
            "phone": "123", "is_active": True,
        }
        for key, value in extra_fields.items():
            with self.subTest(field=key):
                response = self.post({**self.payload, key: value})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_fields")
        self.assertEqual(User.objects.count(), 0)

    def test_missing_fields_are_rejected(self):
        for field in self.payload:
            with self.subTest(field=field):
                payload = {key: value for key, value in self.payload.items() if key != field}
                response = self.post(payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["error"]["fields"])
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_types_empty_fields_and_oversized_password_are_rejected(self):
        invalid = [
            ("username", None), ("username", 123), ("username", "a b"),
            ("displayName", ""), ("displayName", False), ("displayName", []),
            ("password", None), ("password", False), ("password", 123),
            ("password", ""), ("password", "x" * 129),
            ("password", "Bamboo!River-\ud800-7429"),
        ]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                response = self.post({**self.payload, field: value})
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["error"]["fields"])
        self.assertEqual(User.objects.count(), 0)

    def test_password_strength_and_similarity_are_checked(self):
        samples = [
            {**self.payload, "password": "Q7!x"},
            {**self.payload, "password": "12345678901234"},
            {**self.payload, "username": "studentusername01", "password": "studentusername01"},
            {**self.payload, "displayName": "BambooStudentName", "password": "BambooStudentName!"},
        ]
        for payload in samples:
            with self.subTest(case=payload["username"]):
                response = self.post(payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("password", response.json()["error"]["fields"])
                self.assertNotIn(payload["password"], response.content.decode())
        self.assertEqual(User.objects.count(), 0)

    def test_whitespace_only_password_is_rejected(self):
        response = self.post({**self.payload, "password": " " * 16})
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json()["error"]["fields"])
        self.assertEqual(User.objects.count(), 0)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1, DEBUG=True)
    def test_form_body_is_rejected_before_csrf_attempts_to_parse_it(self):
        response = self.client.post("/auth/register", data=self.payload, HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["error"]["code"], "unsupported_media_type")
        self.assertNotIn(self.payload["password"], response.content.decode())
        self.assertEqual(User.objects.count(), 0)

    def test_oversized_json_is_rejected_before_csrf_without_parsing(self):
        response = self.client.generic(
            "POST", "/auth/register", data=b"x" * 9000, content_type="application/json",
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "request_too_large")
        self.assertNotIn("Traceback", response.content.decode())
        self.assertFalse(RateLimitBucket.objects.exists())

    def test_limiter_failure_does_not_allow_registration_or_expose_details(self):
        with patch("accounts.views.registration_limit", side_effect=DatabaseError(self.payload["password"])):
            with self.assertLogs("accounts.views", level="ERROR") as captured:
                response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertEqual(User.objects.count(), 0)
        self.assertNotIn(self.payload["password"], response.content.decode())
        self.assertNotIn(self.payload["password"], " ".join(captured.output))

    def test_duplicate_normalized_username_has_clear_conflict(self):
        self.assertEqual(self.post().status_code, 201)
        response = self.post({**self.payload, "username": " ＳTUDENT01 "})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "username_taken")
        self.assertEqual(User.objects.count(), 1)

    def test_role_assignment_failure_rolls_back_user(self):
        with patch("accounts.services.assign_student_role", side_effect=DatabaseError("test-only failure")):
            with self.assertLogs("accounts.views", level="ERROR"):
                response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(RateLimitBucket.objects.get().attempts, 1)

    def test_missing_student_group_does_not_leave_user(self):
        Group.objects.get(name=STUDENT).delete()
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "registration_unavailable")
        self.assertEqual(User.objects.count(), 0)

    def test_misconfigured_student_permissions_fail_closed(self):
        Group.objects.get(name=STUDENT).permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="change_user"))
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(User.objects.count(), 0)

    def test_csrf_is_required_and_returns_json_without_details(self):
        response = self.client.post("/auth/register", data=self.payload, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "csrf_failed")
        self.assertEqual(User.objects.count(), 0)
        self.assertFalse(RateLimitBucket.objects.exists())

    def test_cross_origin_request_is_rejected_even_with_token(self):
        response = self.post(HTTP_ORIGIN="http://untrusted.example.invalid")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.count(), 0)

    def test_get_cannot_register(self):
        response = self.client.get("/auth/register")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "POST")
        self.assertEqual(response.json()["error"]["code"], "method_not_allowed")

    def test_bad_json_does_not_create_accounts(self):
        samples = ["{", "[]", "null", '{"username":"one","username":"two"}', '{"password":NaN}', b"\xff"]
        for body in samples:
            with self.subTest(body=body):
                response = self.post(body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_json")
        self.assertEqual(User.objects.count(), 0)

    def test_wrong_content_type_and_large_body_are_rejected(self):
        response = self.client.post("/auth/register", data=self.payload, HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(response.status_code, 415)
        response = self.post(json.dumps({**self.payload, "displayName": "x" * 9000}))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(User.objects.count(), 0)

    def test_unsupported_json_encoding_is_rejected(self):
        for charset in ["latin-1", "not-a-real-encoding"]:
            response = self.client.generic(
                "POST", "/auth/register", data=json.dumps(self.payload).encode("utf-8"),
                content_type=f"application/json; charset={charset}", HTTP_X_CSRFTOKEN=self.token,
            )
            self.assertEqual(response.status_code, 415)
        self.assertEqual(User.objects.count(), 0)

    def test_unexpected_error_does_not_expose_password_or_traceback(self):
        with patch("accounts.views.register_student", side_effect=RuntimeError(self.payload["password"])):
            with self.assertLogs("accounts.views", level="ERROR") as captured:
                response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertNotIn(self.payload["password"], response.content.decode())
        self.assertNotIn(self.payload["password"], " ".join(captured.output))

    @override_settings(REGISTER_RATE_LIMIT_MAX_ATTEMPTS=2)
    def test_limit_counts_invalid_attempts_and_has_retry_header(self):
        for _ in range(2):
            self.assertEqual(self.post({}).status_code, 400)
        response = self.post()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "rate_limited")
        self.assertGreater(int(response["Retry-After"]), 0)
        self.assertEqual(User.objects.count(), 0)

    @override_settings(REGISTER_RATE_LIMIT_MAX_ATTEMPTS=1)
    def test_forwarded_header_cannot_bypass_limit(self):
        self.assertEqual(self.post({}, HTTP_X_FORWARDED_FOR="192.0.2.1").status_code, 400)
        response = self.post({}, HTTP_X_FORWARDED_FOR="192.0.2.2")
        self.assertEqual(response.status_code, 429)


class RateLimitTests(TestCase):
    @override_settings(REGISTER_RATE_LIMIT_MAX_ATTEMPTS=1, REGISTER_RATE_LIMIT_WINDOW_SECONDS=60)
    def test_window_expiry_and_ip_separation(self):
        with patch("accounts.rate_limits.time.time", return_value=120):
            self.assertTrue(registration_limit("192.0.2.1").allowed)
            self.assertFalse(registration_limit("192.0.2.1").allowed)
            self.assertTrue(registration_limit("192.0.2.2").allowed)
        with patch("accounts.rate_limits.time.time", return_value=180):
            self.assertTrue(registration_limit("192.0.2.1").allowed)
        for bucket in RateLimitBucket.objects.all():
            self.assertNotIn("192.0.2.", bucket.key)
            self.assertLessEqual(bucket.attempts, 1)

    @override_settings(REGISTER_RATE_LIMIT_MAX_ATTEMPTS=1)
    def test_ipv4_mapped_address_shares_bucket(self):
        self.assertTrue(registration_limit("192.0.2.1").allowed)
        self.assertFalse(registration_limit("::ffff:192.0.2.1").allowed)

    def test_cleanup_preserves_current_and_recently_expired_buckets(self):
        now = timezone.now()
        RateLimitBucket.objects.bulk_create([
            RateLimitBucket(key="old", scope="register", attempts=1, expires_at=now - timedelta(days=2)),
            RateLimitBucket(key="recent", scope="register", attempts=1, expires_at=now - timedelta(minutes=5)),
            RateLimitBucket(key="active", scope="register", attempts=1, expires_at=now + timedelta(minutes=5)),
        ])
        call_command("prune_rate_limits", stdout=StringIO())
        self.assertSetEqual(set(RateLimitBucket.objects.values_list("key", flat=True)), {"recent", "active"})


class ConcurrentRegistrationTests(TransactionTestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())

    def test_same_username_concurrent_http_requests_return_created_and_conflict(self):
        barrier = Barrier(2)

        def register(username):
            close_old_connections()
            try:
                client = Client(enforce_csrf_checks=True)
                token = client.get("/auth/csrf").json()["data"]["csrfToken"]
                barrier.wait(timeout=10)
                response = client.post(
                    "/auth/register", data={"username": username, "displayName": "小明", "password": "Bamboo!River-7429-Cloud"},
                    content_type="application/json", HTTP_X_CSRFTOKEN=token,
                )
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(register, ["Student01", " student01 "]))
        self.assertCountEqual(results, [201, 409])
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(User.objects.get().groups.get().name, STUDENT)

    @override_settings(REGISTER_RATE_LIMIT_MAX_ATTEMPTS=2)
    def test_concurrent_workers_share_a_single_limit(self):
        barrier = Barrier(6)

        def consume(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return registration_limit("192.0.2.9").allowed
            finally:
                close_old_connections()

        with patch("accounts.rate_limits.time.time", return_value=1800):
            with ThreadPoolExecutor(max_workers=6) as executor:
                decisions = list(executor.map(consume, range(6)))
        self.assertEqual(sum(decisions), 2)
        self.assertEqual(RateLimitBucket.objects.get().attempts, 2)

    def test_separate_python_processes_share_a_single_limit(self):
        environment = dict(os.environ, DJANGO_SETTINGS_MODULE="config.test_settings", PYTHONUTF8="1", REGISTER_RATE_LIMIT_MAX_ATTEMPTS="1")
        script = (
            "import django; django.setup(); "
            "from accounts.rate_limits import registration_limit; "
            "import accounts.rate_limits as limits; limits.time.time=lambda:1800; "
            "print(int(registration_limit('192.0.2.77').allowed))"
        )
        children = [subprocess.Popen(
            [sys.executable, "-c", script], cwd=Path(settings.BASE_DIR), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        ) for _ in range(2)]
        results = []
        try:
            for child in children:
                output, error = child.communicate(timeout=20)
                self.assertEqual(child.returncode, 0, error)
                results.append(int(output.strip()))
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
        self.assertCountEqual(results, [1, 0])
        self.assertEqual(RateLimitBucket.objects.get().attempts, 1)
