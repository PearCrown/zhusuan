from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
import json
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import DatabaseError, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from accounts.models import User, MaintenanceEvent, ManualPasswordReset, RateLimitBucket
from accounts.passwords import issue_manual_reset, redeem_manual_reset
from core.api import ApiError

OLD = "Maple!River-7429-Cloud"
NEW = " Copper!Hill-9372-Forest "


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PasswordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.owner = User.objects.create_user("password_owner", password=OLD)
        cls.owner.groups.add(Group.objects.get(name="maintainer"))
        cls.user = User.objects.create_user("password_player", display_name="密码验收同学", password=OLD)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.token = self.client.get("/auth/csrf").json()["data"]["csrfToken"]

    def post(self, path, payload, client=None):
        client = client or self.client
        token = client.get("/auth/csrf").json()["data"]["csrfToken"]
        return client.post(path, payload, content_type="application/json", HTTP_X_CSRFTOKEN=token)

    def change(self, **extra):
        return self.post("/auth/password/change", {"currentPassword": OLD, "newPassword": NEW, **extra})

    def issue(self):
        return issue_manual_reset(self.owner.pk, self.user.pk, User.objects.get(pk=self.user.pk).session_revision, OLD)[0]

    def reset(self, credential, client=None, password=NEW):
        return self.post("/auth/password/reset", {"credential": credential, "newPassword": password}, client)

    def test_change_revokes_current_and_other_devices_preserving_password_spaces(self):
        other = Client()
        other.force_login(self.user)
        response = self.change()
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))
        self.assertFalse(self.user.check_password(NEW.strip()))
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertEqual(other.get("/auth/me").status_code, 401)
        self.assertEqual(MaintenanceEvent.objects.get().action, "password_changed")

    def test_wrong_current_password_cannot_change_or_log_out_user(self):
        response = self.change(currentPassword="wrong-password")
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        self.assertEqual(MaintenanceEvent.objects.count(), 0)

    def test_logout_failure_after_commit_reports_uncertainty_but_old_auth_is_invalid(self):
        with patch("accounts.views.end_login", side_effect=DatabaseError("hidden-secret")):
            with self.assertLogs("accounts.views", level="ERROR"):
                response = self.change()
        self.assertEqual(response.status_code, 503)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertNotIn("hidden-secret", response.content.decode())

    def test_new_password_validation_and_same_password(self):
        for value in ["short", "1234567890123456", " " * 20, OLD, None, [], "x" * 129, "\ud800"]:
            response = self.change(newPassword=value)
            self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))
        self.assertEqual(self.user.session_revision, 0)

    def test_anonymous_change_and_missing_csrf_rejected(self):
        self.assertEqual(self.post("/auth/password/change", {"currentPassword": OLD, "newPassword": NEW}, Client(enforce_csrf_checks=True)).status_code, 401)
        response = self.client.post("/auth/password/change", {"currentPassword": OLD, "newPassword": NEW}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_extra_fields_types_protocol_and_method_rejected(self):
        self.assertEqual(self.change(role="maintainer").status_code, 400)
        for path in ["/auth/password/change", "/auth/password/reset"]:
            self.assertEqual(self.client.get(path).status_code, 405)
            response = self.client.post(path, "bad", content_type="text/plain")
            self.assertEqual(response.status_code, 415)

    def test_change_rate_limit_is_shared_and_independent_of_login(self):
        for _ in range(10):
            self.assertEqual(self.change(currentPassword="wrong-password").status_code, 400)
        self.assertEqual(self.change().status_code, 429)

    def test_password_audit_failure_rolls_back_password_and_ticket_consumption(self):
        credential = self.issue()
        with patch("accounts.passwords.password_audit", side_effect=DatabaseError("secret-password")):
            with self.assertLogs("accounts.views", level="ERROR") as logs:
                response = self.change()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-password", str(logs.output) + response.content.decode())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))
        self.assertIsNone(ManualPasswordReset.objects.get(user=self.user).consumed_at)
        self.assertEqual(self.reset(credential).status_code, 200)

    def test_manual_credential_is_hashed_and_single_use(self):
        credential = self.issue()
        record = ManualPasswordReset.objects.get(user=self.user)
        self.assertNotEqual(record.digest, credential)
        self.assertNotIn(credential, json.dumps(list(MaintenanceEvent.objects.values("before", "after"))))
        anonymous = Client(enforce_csrf_checks=True)
        self.assertEqual(self.reset(credential, anonymous).status_code, 200)
        self.assertEqual(self.reset(credential, anonymous).status_code, 400)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertIsNotNone(ManualPasswordReset.objects.get(user=self.user).consumed_at)

    def test_expired_invalid_consumed_and_reissued_tokens_have_same_error(self):
        old = self.issue()
        current = self.issue()
        errors = [self.reset(old).json()["error"]]
        ManualPasswordReset.objects.filter(user=self.user).update(expires_at=timezone.now() - timedelta(seconds=1))
        errors.append(self.reset(current).json()["error"])
        errors.append(self.reset("not-valid-token").json()["error"])
        self.assertTrue(all(error == errors[0] for error in errors))

    def test_maintenance_revision_disablement_or_privilege_change_invalidates_ticket(self):
        for update in [{"session_revision": 1}, {"is_active": False}, {"is_staff": True}, {"is_superuser": True}]:
            credential = self.issue()
            User.objects.filter(pk=self.user.pk).update(**update)
            self.assertEqual(self.reset(credential).status_code, 400)
            User.objects.filter(pk=self.user.pk).update(session_revision=0, is_active=True, is_staff=False, is_superuser=False)
        credential = self.issue()
        self.user.groups.add(Group.objects.get(name="maintainer"))
        self.assertEqual(self.reset(credential).status_code, 400)

    def test_reset_invalid_password_does_not_consume_ticket(self):
        credential = self.issue()
        self.assertEqual(self.reset(credential, password="short").status_code, 400)
        self.assertIsNone(ManualPasswordReset.objects.get(user=self.user).consumed_at)
        self.assertEqual(self.reset(credential).status_code, 200)

    def test_reset_audit_failure_rolls_back_all_mutations(self):
        credential = self.issue()
        with patch("accounts.passwords.password_audit", side_effect=DatabaseError("secret")):
            with self.assertLogs("accounts.views", level="ERROR"):
                self.assertEqual(self.reset(credential).status_code, 503)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))
        self.assertIsNone(ManualPasswordReset.objects.get(user=self.user).consumed_at)

    def test_successful_change_invalidates_previously_issued_credential(self):
        credential = self.issue()
        self.assertEqual(self.change().status_code, 200)
        self.assertEqual(self.reset(credential, password="Other!Bamboo-3268-Sky").status_code, 400)

    def test_framework_password_change_also_invalidates_previously_issued_ticket(self):
        credential = self.issue()
        self.user.set_password("Changed!Pine-9874-Sky")
        self.user.save(update_fields=["password"])
        self.assertEqual(self.reset(credential).status_code, 400)

    def test_reset_requires_csrf_and_clears_other_browser_identity(self):
        credential = self.issue()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post("/auth/password/reset", {"credential": credential, "newPassword": NEW}, content_type="application/json").status_code, 403)
        self.assertEqual(self.reset(credential, client).status_code, 200)
        self.assertEqual(client.get("/auth/me").status_code, 401)

    def test_issue_rechecks_actor_target_version_and_protected_accounts(self):
        with self.assertRaises(ValidationError):
            issue_manual_reset(self.user.pk, self.user.pk, 0, OLD)
        with self.assertRaises(ValidationError):
            issue_manual_reset(self.owner.pk, self.owner.pk, 0, OLD)
        with self.assertRaises(ValidationError):
            issue_manual_reset(self.owner.pk, self.user.pk, 99, OLD)
        self.assertFalse(ManualPasswordReset.objects.exists())

    def test_issuer_must_reauthenticate_and_reset_requests_are_limited(self):
        with self.assertRaises(ValidationError):
            issue_manual_reset(self.owner.pk, self.user.pk, 0, "wrong-password")
        self.assertFalse(ManualPasswordReset.objects.exists())
        for _ in range(60):
            self.assertEqual(self.reset("invalid-token").status_code, 400)
        self.assertEqual(self.reset("invalid-token").status_code, 429)

    def test_issuance_failure_rolls_back_and_never_exposes_secret(self):
        with patch("accounts.passwords.MaintenanceEvent.objects.create", side_effect=DatabaseError("secret")):
            with self.assertRaises(DatabaseError):
                self.issue()
        self.assertFalse(ManualPasswordReset.objects.exists())

    def test_maintenance_requires_verification_and_displays_token_only_on_issuance_post(self):
        self.client.force_login(self.owner)
        token = self.client.get("/auth/csrf").json()["data"]["csrfToken"]
        data = {"user": self.user.pk, "version": 0, "confirm": "on", "csrfmiddlewaretoken": token, "maintainerPassword": OLD}
        response = self.client.post("/maintenance/password_reset/", data)
        self.assertFalse(ManualPasswordReset.objects.exists())
        self.assertNotContains(response, 'id="manual-reset-link"')
        response = self.client.post("/maintenance/password_reset/", {**data, "verified": "on"})
        self.assertEqual(response.status_code, 200)
        credential = response.context["reset_credential"]
        self.assertTrue(credential)
        self.assertContains(response, 'id="manual-reset-link"')
        self.assertContains(response, 'href="/password/reset/"')
        self.assertContains(response, '先复制上方凭据')
        self.assertNotContains(response, 'class="maintenance-form"')
        self.assertNotContains(response, '可维护账号（')
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self): super().__init__(); self.hrefs=[]
            def handle_starttag(self, tag, attrs):
                if tag == "a": self.hrefs.extend(v for k,v in attrs if k == "href")
        links=Links(); links.feed(response.content.decode())
        self.assertTrue(all(credential not in href for href in links.hrefs))
        self.assertNotContains(self.client.get("/maintenance/password_reset/"), 'id="manual-reset-link"')
        self.assertNotIn(OLD, response.content.decode())
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn(credential, self.client.get("/maintenance/password_reset/").content.decode())
        self.assertNotIn(credential, str(list(MaintenanceEvent.objects.values("before", "after"))))
        for _ in range(2):
            self.assertTrue(self.client.post("/maintenance/password_reset/", {**data, "verified": "on"}).context["reset_credential"])
        self.assertIsNone(self.client.post("/maintenance/password_reset/", {**data, "verified": "on"}).context["reset_credential"])

    def test_pages_are_non_cached_safe_shells_and_post_fallback_cannot_put_secrets_in_url(self):
        for path in ["/password/change/", "/password/reset/"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertContains(response, 'method="post"')
            self.assertEqual(self.client.post(path, {"newPassword": NEW, "csrfmiddlewaretoken": self.token}).status_code, 405)
        self.assertEqual(Client().get("/password/change/").status_code, 403)
        self.assertEqual(Client().get("/password/reset/").status_code, 200)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ResetConcurrencyTests(TransactionTestCase):
    def test_two_consumers_only_one_password_and_audit_commit(self):
        call_command("init_roles", stdout=StringIO())
        owner = User.objects.create_user("reset_race_owner", password=OLD)
        owner.groups.add(Group.objects.get(name="maintainer"))
        user = User.objects.create_user("reset_race_user", password=OLD)
        credential = issue_manual_reset(owner.pk, user.pk, 0, OLD)[0]
        def worker(password):
            connections.close_all()
            try:
                redeem_manual_reset({"credential": credential, "newPassword": password})
                return "success"
            except ApiError as error:
                return error.code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, [NEW, "Other!Bamboo-3268-Sky"]))
        self.assertCountEqual(results, ["success", "reset_invalid"])
        self.assertEqual(MaintenanceEvent.objects.filter(action="password_reset_completed").count(), 1)
