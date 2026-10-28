from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command, CommandError
from django.db import DatabaseError
from django.test import Client, TestCase
from accounts.models import MaintenanceEvent
from accounts.maintenance import apply
from classrooms.models import Classroom, StudentEnrollment, TeacherClassGrant

User = get_user_model()


class MaintenanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.owner = User.objects.create_user("maintainer7", password="River!Bamboo-7932-Cloud")
        cls.owner.groups.add(Group.objects.get(name="maintainer"))
        cls.user = User.objects.create_user("learner7", display_name="维护验收同学", password="Hill!Cloud-8269-Copper")
        cls.a = Classroom.objects.create(code="MA", name="甲班")
        cls.b = Classroom.objects.create(code="MB", name="乙班")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.token = self.client.get("/auth/csrf").json()["data"]["csrfToken"]

    def post(self, action, data):
        return self.client.post(f"/maintenance/{action}/", {"csrfmiddlewaretoken": self.token, "confirm": "on", **data})

    def account(self, **extra):
        return self.post("account", {"user": str(self.user.pk), "version": self.user.session_revision, "active": "on", **extra})

    def test_teacher_student_anonymous_and_superuser_have_no_implicit_access(self):
        superuser = User.objects.create_superuser("root7", password="Root!Cloud-9384-Copper")
        for person in [None, self.user, superuser]:
            client = Client()
            if person:
                client.force_login(person)
            self.assertEqual(client.get("/maintenance/").status_code, 403)
        self.user.groups.add(Group.objects.get(name="teacher"))
        client = Client()
        client.force_login(self.user)
        self.assertEqual(client.get("/maintenance/").status_code, 403)

    def test_requires_csrf_and_does_not_change_on_get(self):
        self.assertEqual(self.client.post("/maintenance/account/", {"user": self.user.pk}).status_code, 403)
        self.assertEqual(self.client.get(f"/maintenance/account/?user={self.user.pk}").status_code, 200)
        self.assertEqual(MaintenanceEvent.objects.count(), 0)

    def test_corrupt_session_identity_is_denied_without_debug_error(self):
        session = self.client.session
        session["_auth_user_id"] = "not-a-uuid"
        session.save()
        self.assertEqual(self.client.get("/maintenance/").status_code, 403)

    def test_unconfirmed_or_duplicate_fields_do_not_modify_state(self):
        response = self.post("account", {"user": self.user.pk, "version": 0, "confirm": ""})
        self.assertEqual(response.status_code, 200)
        response = self.client.post("/maintenance/account/", {"csrfmiddlewaretoken": self.token, "user": self.user.pk, "version": [0, 0], "active": "on", "confirm": "on"})
        self.assertContains(response, "不支持的字段")
        self.assertEqual(MaintenanceEvent.objects.count(), 0)

    def test_maintainer_page_minimum_fields_and_prefilled_account(self):
        response = self.client.get(f"/maintenance/account/?user={self.user.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(response.context["form"].initial["active"])
        self.assertEqual(response.context["form"].initial["version"], 0)
        self.assertNotIn(self.user.password, response.content.decode())
        self.assertNotContains(response, "is_superuser")

    def test_teacher_grant_and_revoke_clears_old_class_grants(self):
        self.assertEqual(self.account(teacher="on").status_code, 302)
        self.user.refresh_from_db()
        TeacherClassGrant.objects.create(teacher=self.user, classroom=self.a)
        self.assertEqual(self.account().status_code, 302)
        self.assertFalse(self.user.groups.filter(name="teacher").exists())
        self.assertFalse(TeacherClassGrant.objects.filter(teacher=self.user).exists())
        self.assertEqual(MaintenanceEvent.objects.count(), 2)
        event = MaintenanceEvent.objects.latest("pk")
        self.assertEqual(event.before["teachingClassIds"], [str(self.a.pk)])
        self.assertEqual(event.after["teachingClassIds"], [])

    def test_extra_privilege_fields_rejected_and_protected_accounts_unselectable(self):
        response = self.account(is_superuser="on")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "不支持的字段")
        self.user.refresh_from_db()
        self.assertEqual(self.user.session_revision, 0)
        response = self.post("account", {"user": self.owner.pk, "version": 0, "active": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MaintenanceEvent.objects.count(), 0)

    def test_stale_version_cannot_overwrite_new_state(self):
        self.assertEqual(self.account(teacher="on").status_code, 302)
        response = self.account()
        self.assertContains(response, "记录已变化")
        self.assertTrue(self.user.groups.filter(name="teacher").exists())
        self.assertEqual(MaintenanceEvent.objects.count(), 1)

    def test_audit_failure_rolls_back_role_and_version(self):
        with patch("accounts.maintenance.record", side_effect=DatabaseError("hidden-secret")):
            with self.assertLogs("accounts.maintenance", level="ERROR") as logs:
                response = self.account(teacher="on")
        self.assertEqual(response.status_code, 503)
        self.user.refresh_from_db()
        self.assertEqual(self.user.session_revision, 0)
        self.assertFalse(self.user.groups.filter(name="teacher").exists())
        self.assertNotIn("hidden-secret", str(logs.output) + response.content.decode())

    def test_disabled_reenabled_never_presented_sessions_stay_invalid_on_all_devices(self):
        devices = [Client(), Client()]
        for client in devices:
            client.force_login(self.user)
        self.assertEqual(self.post("account", {"user": self.user.pk, "version": 0}).status_code, 302)
        self.assertEqual(self.post("account", {"user": self.user.pk, "version": 1, "active": "on"}).status_code, 302)
        for client in devices:
            self.assertEqual(client.get("/auth/me").status_code, 401)
        fresh = Client()
        fresh.force_login(User.objects.get(pk=self.user.pk))
        self.assertEqual(fresh.get("/auth/me").status_code, 200)

    def test_class_create_update_duplicate_and_audit(self):
        self.assertEqual(self.post("create_class", {"code": "MC", "name": "丙班"}).status_code, 302)
        response = self.post("create_class", {"code": "MC", "name": "重复班"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Classroom.objects.filter(code="MC").count(), 1)
        self.assertEqual(self.post("class", {"classroom": self.a.pk, "version": 0, "code": "MA", "name": "改名甲班"}).status_code, 302)
        self.a.refresh_from_db()
        self.assertFalse(self.a.is_active)
        self.assertEqual(self.a.maintenance_version, 1)
        response = self.post("class", {"classroom": self.a.pk, "version": 0, "code": "MA", "name": "旧名"})
        self.assertContains(response, "记录已变化")

    def test_enrollment_transfer_and_clear(self):
        for version, classroom in [(0, self.a.pk), (1, self.b.pk), (2, "")]:
            self.assertEqual(self.post("enrollment", {"user": self.user.pk, "version": version, "classroom": classroom}).status_code, 302)
        self.assertFalse(StudentEnrollment.objects.filter(student=self.user).exists())
        self.assertEqual(MaintenanceEvent.objects.count(), 3)

    def test_grant_requires_teacher_and_active_class_but_revoke_inactive_allowed(self):
        data = {"user": self.user.pk, "version": 0, "classroom": self.a.pk, "grant": "on"}
        self.assertContains(self.post("grant", data), "需要启用的教师")
        self.user.groups.add(Group.objects.get(name="teacher"))
        self.assertEqual(self.post("grant", data).status_code, 302)
        self.a.is_active = False
        self.a.save()
        self.assertEqual(self.post("grant", {"user": self.user.pk, "version": 1, "classroom": self.a.pk}).status_code, 302)
        self.assertFalse(TeacherClassGrant.objects.exists())

    def test_revoked_maintainer_denied_next_request(self):
        self.owner.groups.clear()
        self.assertEqual(self.client.get("/maintenance/").status_code, 403)

    def test_unknown_maintenance_action_does_not_fall_through_to_grant(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            apply(self.owner.pk, "password_reset", {})

    def test_bootstrap_is_audited_without_staff_and_last_revoke_refused(self):
        call_command("provision_maintainer", self.user.username, stdout=StringIO())
        self.user.refresh_from_db()
        self.assertTrue(self.user.groups.filter(name="maintainer").exists())
        self.assertFalse(self.user.is_staff)
        self.assertEqual(MaintenanceEvent.objects.get().action, "bootstrap_maintainer")
        call_command("provision_maintainer", self.user.username, revoke=True, stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("provision_maintainer", self.owner.username, revoke=True, stdout=StringIO())
