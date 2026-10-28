from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.db import DatabaseError
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts.models import RateLimitBucket
from accounts.authentication import login_required_api
from accounts.roles import STUDENT, TEACHER
from classrooms.models import Classroom, StudentEnrollment, TeacherClassGrant

User = get_user_model()
PASSWORD = "Bamboo!River-7429-Cloud"


class SessionApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.alice = User.objects.create_user("alice01", display_name="小明", password=PASSWORD)
        cls.bob = User.objects.create_user("bob0001", display_name="小红", password=PASSWORD)
        cls.alice.groups.add(Group.objects.get(name=STUDENT))
        cls.bob.groups.add(Group.objects.get(name=STUDENT))

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.token = self.client.get("/auth/csrf").json()["data"]["csrfToken"]

    def post(self, path, payload, *, token=None, client=None, **extra):
        client = client or self.client
        response = client.post(path, data=payload, content_type="application/json", HTTP_X_CSRFTOKEN=token or self.token, **extra)
        if client is self.client and response.status_code == 200:
            self.token = response.json().get("data", {}).get("csrfToken", self.token)
        return response

    def login(self, username="alice01", password=PASSWORD, **extra):
        return self.post("/auth/login", {"username": username, "password": password}, **extra)

    def test_login_saves_cookie_and_only_basic_identity(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        identity = response.json()["data"]["user"]
        self.assertEqual(identity, {
            "userId": str(self.alice.pk), "username": "alice01", "displayName": "小明",
            "roles": ["student"], "classId": None, "teachingClassIds": [],
        })
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertTrue(Session.objects.filter(session_key=cookie.value).exists())
        self.assertNotIn(cookie.value, response.content.decode())
        self.assertNotIn(PASSWORD, response.content.decode())
        self.assertNotIn(self.alice.password, response.content.decode())
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_new_browser_request_with_same_cookie_retains_identity(self):
        self.assertEqual(self.login().status_code, 200)
        another = Client(enforce_csrf_checks=True)
        another.cookies[settings.SESSION_COOKIE_NAME] = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        response = another.get("/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["userId"], str(self.alice.pk))
        self.assertIn("Cookie", response["Vary"])

    def test_unknown_bad_password_and_inactive_account_have_identical_error(self):
        unknown = self.login("unknown01").json()
        wrong = self.login(password="Wrong-password-921!").json()
        User.objects.filter(pk=self.alice.pk).update(is_active=False)
        inactive = self.login().json()
        self.assertEqual(unknown, wrong)
        self.assertEqual(inactive, wrong)
        self.assertEqual(wrong["error"]["code"], "invalid_credentials")
        self.assertEqual(Session.objects.count(), 0)

    def test_missing_or_malformed_fields_do_not_authenticate(self):
        for payload in [{}, {"username": "alice01"}, {"username": False, "password": PASSWORD}, {"username": "alice01", "password": None}, {"username": "alice01", "password": "Bamboo!\ud800-921"}]:
            with self.subTest(payload=payload):
                response = self.post("/auth/login", payload)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Session.objects.count(), 0)

    def test_client_cannot_choose_user_or_role_when_logging_in(self):
        for key, value in [("role", "teacher"), ("userId", str(self.bob.pk)), ("next", "https://untrusted.example.invalid")]:
            response = self.post("/auth/login", {"username": "alice01", "password": PASSWORD, key: value})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(Session.objects.count(), 0)

    def test_login_does_not_reapply_new_registration_strength_rules(self):
        self.alice.set_password("p@ss")
        self.alice.save(update_fields=["password"])
        self.assertEqual(self.login(password="p@ss").status_code, 200)

    def test_login_preserves_password_spaces(self):
        original = "  Bamboo!River-7429-Cloud  "
        self.alice.set_password(original)
        self.alice.save(update_fields=["password"])
        self.assertEqual(self.login(password=original.strip()).status_code, 401)
        self.assertEqual(self.login(password=original).status_code, 200)

    def test_session_id_is_replaced_even_for_same_user_login(self):
        self.assertEqual(self.login().status_code, 200)
        previous = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(self.login().status_code, 200)
        current = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertNotEqual(previous, current)
        self.assertFalse(Session.objects.filter(session_key=previous).exists())
        replay = Client()
        replay.cookies[settings.SESSION_COOKIE_NAME] = previous
        self.assertEqual(replay.get("/auth/me").status_code, 401)

    def test_switching_accounts_replaces_previous_identity_and_session(self):
        self.assertEqual(self.login().status_code, 200)
        previous = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        response = self.login("bob0001")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["user"]["userId"], str(self.bob.pk))
        self.assertFalse(Session.objects.filter(session_key=previous).exists())
        self.assertEqual(self.client.get("/auth/me").json()["data"]["userId"], str(self.bob.pk))

    def test_failed_account_switch_keeps_existing_identity(self):
        self.assertEqual(self.login().status_code, 200)
        previous = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(self.login("bob0001", "Wrong-password-921!").status_code, 401)
        self.assertEqual(self.client.cookies[settings.SESSION_COOKIE_NAME].value, previous)
        self.assertEqual(self.client.get("/auth/me").json()["data"]["userId"], str(self.alice.pk))

    def test_missing_or_forged_cookie_returns_json_401_not_redirect(self):
        for cookie in [None, "nonexistent-session-key-abcdefghijk"]:
            client = Client()
            if cookie:
                client.cookies[settings.SESSION_COOKIE_NAME] = cookie
            response = client.get("/auth/me")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "authentication_required")
            self.assertNotIn("Location", response)

    def test_reusable_login_guard_returns_json_without_extra_wrapper(self):
        @login_required_api
        def protected(request):
            raise AssertionError("unauthenticated user reached protected action")

        request = RequestFactory().get("/sample/protected")
        request.user = AnonymousUser()
        request.session = SessionStore()
        response = protected(request)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_disabled_account_next_request_revokes_presented_session(self):
        self.assertEqual(self.login().status_code, 200)
        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        User.objects.filter(pk=self.alice.pk).update(is_active=False)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        User.objects.filter(pk=self.alice.pk).update(is_active=True)
        self.client.cookies[settings.SESSION_COOKIE_NAME] = key
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_expired_session_returns_401_and_clears_cookie(self):
        self.assertEqual(self.login().status_code, 200)
        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timedelta(seconds=1))
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]["max-age"], 0)

    def test_reading_identity_does_not_extend_absolute_expiry(self):
        before = timezone.now()
        self.assertEqual(self.login().status_code, 200)
        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        expiry = Session.objects.get(session_key=key).expire_date
        self.assertGreater(expiry, before)
        self.assertLessEqual(expiry, timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE))
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        self.assertEqual(Session.objects.get(session_key=key).expire_date, expiry)

    def test_malformed_stored_user_id_is_cleared_as_unauthenticated(self):
        session = self.client.session
        session[SESSION_KEY] = "not-a-valid-uuid"
        session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        session[HASH_SESSION_KEY] = "invalid-hash"
        session.save()
        key = session.session_key
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(Session.objects.filter(session_key=key).exists())

    def test_identity_roles_and_classes_are_read_fresh(self):
        self.assertEqual(self.login().status_code, 200)
        a = Classroom.objects.create(code="class-a", name="甲班")
        b = Classroom.objects.create(code="class-b", name="乙班", is_active=False)
        StudentEnrollment.objects.create(student=self.alice, classroom=a)
        TeacherClassGrant.objects.create(teacher=self.alice, classroom=a)
        TeacherClassGrant.objects.create(teacher=self.alice, classroom=b)
        self.alice.groups.add(Group.objects.get(name=TEACHER))
        identity = self.client.get("/auth/me").json()["data"]
        self.assertEqual(identity["roles"], ["student", "teacher"])
        self.assertEqual(identity["classId"], str(a.pk))
        self.assertEqual(identity["teachingClassIds"], [str(a.pk)])
        self.alice.groups.remove(Group.objects.get(name=TEACHER))
        identity = self.client.get("/auth/me").json()["data"]
        self.assertEqual(identity["roles"], ["student"])
        self.assertEqual(identity["teachingClassIds"], [])

    def test_logout_revokes_server_session_and_copied_cookie(self):
        self.assertEqual(self.login().status_code, 200)
        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        response = self.post("/auth/logout", {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["loggedOut"])
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        replay = Client()
        replay.cookies[settings.SESSION_COOKIE_NAME] = key
        self.assertEqual(replay.get("/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_logout_is_idempotent_with_valid_csrf(self):
        self.assertEqual(self.post("/auth/logout", {}).status_code, 200)
        self.assertEqual(self.post("/auth/logout", {}).status_code, 200)

    def test_get_logout_or_extra_fields_cannot_log_out(self):
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/auth/logout").status_code, 405)
        self.assertEqual(self.post("/auth/logout", {"userId": str(self.bob.pk)}).status_code, 400)
        self.assertEqual(self.client.get("/auth/me").status_code, 200)

    def test_login_and_logout_require_csrf_and_reject_old_token(self):
        response = self.client.post("/auth/login", {"username": "alice01", "password": PASSWORD}, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        old_token = self.token
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.post("/auth/logout", {}, token=old_token).status_code, 403)
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        self.assertEqual(self.post("/auth/logout", {}).status_code, 200)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1, DEBUG=True)
    def test_login_wrong_form_is_rejected_before_framework_parsing(self):
        response = self.client.post("/auth/login", {"username": "alice01", "password": PASSWORD}, HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["error"]["code"], "unsupported_media_type")

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1, DEBUG=True)
    def test_read_only_api_rejects_post_before_form_parsing(self):
        for path in ["/auth/csrf", "/auth/me"]:
            response = self.client.post(path, {"username": "alice01", "password": PASSWORD})
            self.assertEqual(response.status_code, 405)
            self.assertEqual(response.json()["error"]["code"], "method_not_allowed")
            self.assertEqual(response["Allow"], "GET, HEAD")
            self.assertNotIn(PASSWORD, response.content.decode())
        self.assertEqual(Session.objects.count(), 0)

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_secure_cookie_flags_are_emitted_when_configured(self):
        response = self.login(secure=True, HTTP_ORIGIN="https://testserver")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies[settings.SESSION_COOKIE_NAME]["secure"])
        self.assertTrue(response.cookies[settings.CSRF_COOKIE_NAME]["secure"])

    def test_password_change_invalidates_existing_session_hash(self):
        self.assertEqual(self.login().status_code, 200)
        self.alice.set_password("Changed!River-8934-Bamboo")
        self.alice.save(update_fields=["password"])
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_session_load_database_failure_returns_safe_503(self):
        self.assertEqual(self.login().status_code, 200)
        with patch.object(SessionStore, "load", side_effect=DatabaseError(PASSWORD)):
            with self.assertLogs("accounts.views", level="ERROR") as captured:
                response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(PASSWORD, response.content.decode())
        self.assertNotIn(PASSWORD, " ".join(captured.output))

    def test_post_view_session_save_failure_cannot_return_login_success(self):
        original_save = SessionStore.save

        def fail_authenticated(store, *args, **kwargs):
            if store.get(SESSION_KEY):
                raise DatabaseError(PASSWORD)
            return original_save(store, *args, **kwargs)

        with patch.object(SessionStore, "save", new=fail_authenticated):
            with self.assertLogs("core.middleware", level="ERROR") as captured:
                response = self.login()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn(PASSWORD, response.content.decode())
        self.assertNotIn(PASSWORD, " ".join(captured.output))
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertTrue(all(SESSION_KEY not in row.get_decoded() for row in Session.objects.all()))

    def test_concurrently_removed_session_returns_json_401(self):
        original_save = SessionStore.save

        def interrupted(store, *args, **kwargs):
            if store.get(SESSION_KEY):
                raise UpdateError
            return original_save(store, *args, **kwargs)

        with patch.object(SessionStore, "save", new=interrupted):
            response = self.login()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]["max-age"], 0)

    @override_settings(LOGIN_ACCOUNT_IP_RATE_LIMIT_MAX_ATTEMPTS=1)
    def test_login_account_limit_uses_normalized_name(self):
        self.assertEqual(self.login(password="Wrong-password-921!").status_code, 401)
        response = self.login(" ＡLICE01 ", PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response["Retry-After"]), 0)
        self.assertEqual(Session.objects.count(), 0)

    @override_settings(LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS=1)
    def test_login_ip_limit_ignores_forwarded_headers(self):
        self.assertEqual(self.login(password="Wrong-password-921!", HTTP_X_FORWARDED_FOR="192.0.2.1").status_code, 401)
        self.assertEqual(self.login("bob0001", HTTP_X_FORWARDED_FOR="192.0.2.2").status_code, 429)
        self.assertEqual(self.login("bob0001", REMOTE_ADDR="192.0.2.7").status_code, 200)

    @override_settings(LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS=1, REGISTER_RATE_LIMIT_MAX_ATTEMPTS=1)
    def test_registration_and_login_limits_are_independent(self):
        self.assertEqual(self.login(password="Wrong-password-921!").status_code, 401)
        response = self.post("/auth/register", {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.login().status_code, 429)
        self.assertSetEqual(set(RateLimitBucket.objects.values_list("scope", flat=True)), {"register", "login-ip", "login-account-ip"})

    def test_login_limiter_failure_does_not_authenticate(self):
        with patch("accounts.views.login_ip_limit", side_effect=DatabaseError(PASSWORD)):
            with self.assertLogs("accounts.views", level="ERROR"):
                response = self.login()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Session.objects.count(), 0)

    def test_logout_does_not_revoke_another_device_session(self):
        self.assertEqual(self.login().status_code, 200)
        other = Client(enforce_csrf_checks=True)
        token = other.get("/auth/csrf").json()["data"]["csrfToken"]
        response = other.post("/auth/login", {"username": "alice01", "password": PASSWORD}, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.post("/auth/logout", {}).status_code, 200)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertEqual(other.get("/auth/me").status_code, 200)

    def test_cross_origin_login_is_rejected_with_valid_csrf(self):
        response = self.login(HTTP_ORIGIN="http://untrusted.example.invalid")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Session.objects.count(), 0)

    def test_logout_database_failure_is_not_reported_as_success(self):
        self.assertEqual(self.login().status_code, 200)
        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        with patch.object(SessionStore, "delete", side_effect=DatabaseError(PASSWORD)):
            with self.assertLogs("accounts.views", level="ERROR"):
                response = self.post("/auth/logout", {})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(PASSWORD, response.content.decode())
        self.assertTrue(Session.objects.filter(session_key=key).exists())
        self.assertEqual(self.post("/auth/logout", {}).status_code, 200)
        self.assertFalse(Session.objects.filter(session_key=key).exists())

    def test_disable_between_password_check_and_session_creation_is_rechecked(self):
        from django.contrib.auth import authenticate

        def disable_after_check(*args, **kwargs):
            user = authenticate(*args, **kwargs)
            User.objects.filter(pk=user.pk).update(is_active=False)
            return user

        with patch("accounts.services.authenticate", side_effect=disable_after_check):
            response = self.login()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credentials")
        self.assertEqual(Session.objects.count(), 0)

    def test_password_change_between_check_and_session_creation_is_rechecked(self):
        from django.contrib.auth import authenticate
        from django.contrib.auth.hashers import make_password

        replacement = make_password("Changed!River-8934-Bamboo")

        def change_after_check(*args, **kwargs):
            user = authenticate(*args, **kwargs)
            User.objects.filter(pk=user.pk).update(password=replacement)
            return user

        with patch("accounts.services.authenticate", side_effect=change_after_check):
            response = self.login()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Session.objects.count(), 0)
