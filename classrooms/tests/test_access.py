import csv
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import DatabaseError
from django.test import Client, TestCase

from classrooms.access import EXPORT_ROSTER, teacher_classes
from classrooms.models import Classroom, StudentEnrollment, TeacherClassGrant
from classrooms.views import csv_cell
from core.api import ApiError

User = get_user_model()
BASE = "/teacher/api/classes"


class TeacherAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.teacher = User.objects.create_user("teachera", display_name="甲老师")
        cls.other = User.objects.create_user("teacherb", display_name="乙老师")
        cls.student = User.objects.create_user("studenta", display_name="甲同学")
        cls.foreign = User.objects.create_user("studentb", display_name="乙同学")
        cls.maintainer = User.objects.create_user("maintainer", display_name="维护员")
        cls.superuser = User.objects.create_superuser("emergency", display_name="应急管理员", password="River!Copper-3928-Hill")
        cls.teacher.groups.add(Group.objects.get(name="teacher"))
        cls.other.groups.add(Group.objects.get(name="teacher"))
        cls.student.groups.add(Group.objects.get(name="student"))
        cls.maintainer.groups.add(Group.objects.get(name="maintainer"))
        cls.first = Classroom.objects.create(code="A01", name="一班")
        cls.second = Classroom.objects.create(code="B01", name="二班")
        cls.inactive = Classroom.objects.create(code="C01", name="停用班", is_active=False)
        TeacherClassGrant.objects.create(teacher=cls.teacher, classroom=cls.first)
        TeacherClassGrant.objects.create(teacher=cls.teacher, classroom=cls.inactive)
        TeacherClassGrant.objects.create(teacher=cls.other, classroom=cls.second)
        StudentEnrollment.objects.create(student=cls.student, classroom=cls.first)
        StudentEnrollment.objects.create(student=cls.foreign, classroom=cls.second)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def login(self, user=None):
        self.client.force_login(user or self.teacher)

    def roster(self, classroom=None, csv=False):
        return f"{BASE}/{(classroom or self.first).pk}/students{'.csv' if csv else ''}"

    def permission(self, codename):
        return Permission.objects.get(content_type__app_label="classrooms", content_type__model="classroom", codename=codename)

    def test_anonymous_denied_on_all_data_entry_points(self):
        for path in [BASE, self.roster(), self.roster(csv=True)]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "authentication_required")
            self.assertNotIn("Location", response)

    def test_student_maintainer_superuser_or_grant_alone_cannot_be_teacher(self):
        TeacherClassGrant.objects.create(teacher=self.student, classroom=self.first)
        self.maintainer.user_permissions.add(self.permission("view_class_progress"), self.permission(EXPORT_ROSTER))
        for user in [self.student, self.maintainer, self.superuser]:
            self.login(user)
            for path in [BASE, self.roster(), self.roster(csv=True)]:
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_only_current_active_authorized_classes_are_listed(self):
        self.login()
        response = self.client.get(BASE)
        data = response.json()["data"]
        self.assertEqual(data["items"], [{"classId": str(self.first.pk), "code": "A01", "name": "一班"}])
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["pageSize"], 50)
        self.assertFalse(data["hasNext"])
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("Cookie", response["Vary"])

    def test_teacher_can_have_multiple_explicit_classes(self):
        TeacherClassGrant.objects.create(teacher=self.teacher, classroom=self.second)
        self.login()
        self.assertEqual(self.client.get(BASE).json()["data"]["total"], 2)

    def test_teacher_without_student_role_still_uses_account_identity(self):
        self.login()
        self.assertEqual(self.client.get("/auth/me").json()["data"]["roles"], ["teacher"])
        self.assertFalse(self.teacher.is_staff)

    def test_no_grants_is_empty_not_all_classes(self):
        TeacherClassGrant.objects.filter(teacher=self.teacher).delete()
        self.login()
        self.assertEqual(self.client.get(BASE).json()["data"]["items"], [])

    def test_unknown_foreign_inactive_and_invalid_uuid_share_same_response(self):
        self.login()
        errors = []
        for key in [self.second.pk, self.inactive.pk, uuid4(), "invalid-id"]:
            for ending in ["students", "students.csv"]:
                response = self.client.get(f"{BASE}/{key}/{ending}")
                self.assertEqual(response.status_code, 404)
                errors.append(response.json())
                self.assertNotIn(self.foreign.display_name, response.content.decode())
        self.assertTrue(all(error == errors[0] for error in errors))

    def test_roster_returns_only_active_current_members_and_minimum_fields(self):
        disabled = User.objects.create_user("disabled", display_name="停用同学", is_active=False)
        StudentEnrollment.objects.create(student=disabled, classroom=self.first)
        self.student.email = "private@example.invalid"
        self.student.save(update_fields=["email"])
        self.login()
        response = self.client.get(self.roster())
        data = response.json()["data"]
        self.assertEqual(data["items"], [{"userId": str(self.student.pk), "username": "studenta", "displayName": "甲同学"}])
        self.assertNotIn("private@example", response.content.decode())
        self.assertNotIn("password", response.content.decode())

    def test_teacher_may_be_enrolled_learner_without_student_group(self):
        StudentEnrollment.objects.create(student=self.other, classroom=self.first)
        self.login()
        self.assertEqual(self.client.get(self.roster()).json()["data"]["total"], 2)

    def test_reassignment_removes_student_from_previous_class_next_request(self):
        self.login()
        self.assertEqual(self.client.get(self.roster()).json()["data"]["total"], 1)
        StudentEnrollment.objects.filter(student=self.student).update(classroom=self.second)
        self.assertEqual(self.client.get(self.roster()).json()["data"]["items"], [])

    def test_role_revocation_applies_to_list_roster_and_export(self):
        self.login()
        self.assertEqual(self.client.get(BASE).status_code, 200)
        self.teacher.groups.clear()
        for path in [BASE, self.roster(), self.roster(csv=True)]:
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_class_grant_revocation_applies_next_request(self):
        self.login()
        self.assertEqual(self.client.get(self.roster()).status_code, 200)
        TeacherClassGrant.objects.filter(teacher=self.teacher, classroom=self.first).delete()
        self.assertEqual(self.client.get(self.roster()).status_code, 404)
        self.assertEqual(self.client.get(self.roster(csv=True)).status_code, 404)
        self.assertEqual(self.client.get(BASE).json()["data"]["items"], [])

    def test_class_disablement_removes_data_next_request(self):
        self.login()
        self.first.is_active = False
        self.first.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.roster()).status_code, 404)
        self.assertEqual(self.client.get(self.roster(csv=True)).status_code, 404)

    def test_user_disablement_denies_next_teacher_request(self):
        self.login()
        User.objects.filter(pk=self.teacher.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.roster()).status_code, 401)

    def test_view_permission_revocation_also_prevents_export(self):
        self.login()
        Group.objects.get(name="teacher").permissions.remove(self.permission("view_class_progress"))
        for path in [BASE, self.roster(), self.roster(csv=True)]:
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_export_permission_is_separate_from_read_permission(self):
        self.login()
        Group.objects.get(name="teacher").permissions.remove(self.permission(EXPORT_ROSTER))
        self.assertEqual(self.client.get(self.roster()).status_code, 200)
        self.assertEqual(self.client.get(self.roster(csv=True)).status_code, 403)

    def test_guard_does_not_trust_django_permission_cache(self):
        self.assertTrue(self.teacher.has_perm("classrooms.view_class_progress"))
        Group.objects.get(name="teacher").permissions.remove(self.permission("view_class_progress"))
        with self.assertRaises(ApiError) as caught:
            teacher_classes(self.teacher)
        self.assertEqual(caught.exception.status, 403)

    def test_unknown_guard_action_fails_closed(self):
        with self.assertRaises(ValueError):
            teacher_classes(self.teacher, action="misspelled_action")

    def test_unexpected_or_duplicate_query_parameters_never_override_identity(self):
        self.login()
        for query in ["role=teacher", "userId=someone", "classId=other", "page=1&page=2", "page=0", "page=-1", "page=100001", "page=abc", "page=%EF%BC%91"]:
            for path in [BASE, self.roster()]:
                self.assertEqual(self.client.get(path + "?" + query).status_code, 400)
        self.assertEqual(self.client.get(self.roster(csv=True) + "?page=1").status_code, 400)

    def test_wrong_methods_rejected_before_form_parsing_or_csrf(self):
        for path in [BASE, self.roster(), self.roster(csv=True)]:
            response = self.client.post(path, data=b"broken", content_type="application/x-www-form-urlencoded")
            self.assertEqual(response.status_code, 405)
            self.assertEqual(response.json()["error"]["code"], "method_not_allowed")

    def test_head_keeps_authorization_and_has_no_body(self):
        self.login()
        for path in [BASE, self.roster(), self.roster(csv=True)]:
            response = self.client.head(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")
        self.assertEqual(self.client.head(self.roster(self.second)).status_code, 404)

    def test_csv_is_scoped_utf8_and_protected_against_spreadsheet_formulas(self):
        self.student.display_name = "=SUM(1,2)"
        self.student.save(update_fields=["display_name"])
        self.login()
        response = self.client.get(self.roster(csv=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertNotIn(self.first.name, response["Content-Disposition"])
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows, [["用户编号", "用户名", "显示名称"], [str(self.student.pk), "studenta", "'=SUM(1,2)"]])
        self.assertNotIn("studentb", response.content.decode())
        for text in ["=1+1", "+2", "-3", "@SUM(A1)", "  =7", "\t7", "\r8", "\n9"]:
            self.assertTrue(csv_cell(text).startswith("'"))
        self.assertEqual(csv_cell("正常名字"), "正常名字")

    def test_export_limit_refuses_instead_of_silently_truncating(self):
        self.login()
        with patch("classrooms.views.MAX_EXPORT_STUDENTS", 0):
            response = self.client.get(self.roster(csv=True))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "export_too_large")

    def test_database_failure_is_json_not_partial_csv_or_secret(self):
        self.login()
        with patch("classrooms.views.students_in", side_effect=DatabaseError("secret-db-password")):
            with self.assertLogs("classrooms.views", level="ERROR") as logs:
                response = self.client.get(self.roster(csv=True))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("secret-db-password", response.content.decode() + str(logs.output))
        self.assertNotIn("Content-Disposition", response)

    def test_class_list_paginates_without_listing_foreign_class(self):
        classes = [Classroom(code=f"T{i:03}", name=f"测试{i}") for i in range(51)]
        Classroom.objects.bulk_create(classes)
        TeacherClassGrant.objects.bulk_create([TeacherClassGrant(teacher=self.teacher, classroom=c) for c in classes])
        self.login()
        first = self.client.get(BASE).json()["data"]
        second = self.client.get(BASE + "?page=2").json()["data"]
        self.assertEqual((len(first["items"]), len(second["items"])), (50, 2))
        self.assertTrue(first["hasNext"])
        self.assertFalse(second["hasNext"])
        self.assertEqual(len({row["classId"] for row in first["items"] + second["items"]}), 52)

    def test_roster_paginates_members(self):
        users = [User(username=f"page{i:03}", display_name=f"同学{i}", password="!") for i in range(51)]
        User.objects.bulk_create(users)
        StudentEnrollment.objects.bulk_create([StudentEnrollment(student=u, classroom=self.first) for u in users])
        self.login()
        first = self.client.get(self.roster()).json()["data"]
        second = self.client.get(self.roster() + "?page=2").json()["data"]
        self.assertEqual((len(first["items"]), len(second["items"])), (50, 2))
        self.assertEqual(first["total"], 52)
        self.assertEqual(len({row["userId"] for row in first["items"] + second["items"]}), 52)

    def test_workspace_is_public_non_cached_shell_without_student_data(self):
        response = self.client.get("/teacher/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn(self.student.username, response.content.decode())
        self.assertContains(response, 'id="roster" aria-labelledby="roster-title" hidden')
