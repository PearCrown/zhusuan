from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase

from accounts.roles import MAINTAINER, STUDENT, TEACHER
from classrooms.models import Classroom, StudentEnrollment, TeacherClassGrant

User = get_user_model()


class UserFoundationTests(TestCase):
    def test_custom_model_and_no_default_user_table(self):
        self.assertEqual(User._meta.label, "accounts.User")
        self.assertNotIn("auth_user", connection.introspection.table_names())

    def test_username_canonicalization_and_chinese_name(self):
        user = User.objects.create_user("  Ａlice_01  ", display_name=" 小明 ", password=None)
        user.refresh_from_db()
        self.assertEqual(user.username, "alice_01")
        self.assertEqual(user.display_name, "小明")
        self.assertIsInstance(user.pk, uuid.UUID)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())

    def test_equivalent_usernames_cannot_create_two_accounts(self):
        User.objects.create_user("Alice", password=None)
        for username in ["alice", " ALICE ", "Ａｌｉｃｅ"]:
            with self.subTest(username=username):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    User.objects.create_user(username, password=None)
        self.assertEqual(User.objects.count(), 1)

    def test_natural_key_uses_same_normalization(self):
        user = User.objects.create_user("Alice", password=None)
        self.assertEqual(User.objects.get_by_natural_key(" ALICE "), user)
        with self.assertRaises(User.DoesNotExist):
            User.objects.get_by_natural_key("非法用户名")

    def test_database_rejects_noncanonical_username_when_save_is_bypassed(self):
        user = User.objects.create_user("alice", password=None)
        for username in ["ALICE", " alice ", "Ａlice", "alice\n"]:
            with self.subTest(username=username):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    User.objects.filter(pk=user.pk).update(username=username)

    def test_invalid_usernames_rejected(self):
        for username in ["", "ab", "a" * 33, "a b", "a@b", "_alice", "用户一"]:
            with self.subTest(username=username):
                with self.assertRaises(ValidationError):
                    User.objects.create_user(username, password=None)

    def test_bad_display_names_rejected(self):
        for name in ["   ", "x" * 61, "name\nother", "小\u200b明"]:
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    User.objects.create_user("student01", display_name=name, password=None)

    def test_explicit_empty_or_nontext_display_name_is_not_silently_replaced(self):
        for name in ["", None, False, [], 0]:
            with self.subTest(name=name), transaction.atomic(), self.assertRaises(ValidationError):
                User.objects.create_user("student01", display_name=name, password=None)

    def test_password_is_hashed_and_verifiable(self):
        password = "Testing-only-passphrase-42!"
        user = User.objects.create_user("student01", password=password)
        self.assertNotEqual(user.password, password)
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.check_password("wrong"))

    def test_renaming_does_not_change_user_identity_or_class(self):
        user = User.objects.create_user("student01", password=None)
        classroom = Classroom.objects.create(code="class-a", name="甲班")
        enrollment = StudentEnrollment.objects.create(student=user, classroom=classroom)
        original_id = user.pk
        user.username = "student02"
        user.display_name = "新名字"
        user.save()
        enrollment.refresh_from_db()
        self.assertEqual(user.pk, original_id)
        self.assertEqual(enrollment.student_id, original_id)

    def test_ordinary_creation_cannot_grant_maintenance_flags(self):
        for flag in ["is_staff", "is_superuser"]:
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                User.objects.create_user("student01", password=None, **{flag: True})
        self.assertEqual(User.objects.count(), 0)

    def test_explicit_superuser_creation_still_works(self):
        user = User.objects.create_superuser("localadmin", password="Testing-only-admin-passphrase-42!")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    async def test_async_creation_and_lookup_use_same_rules(self):
        user = await User.objects.acreate_user(" Ａlice ", display_name=" 小明 ", password=None)
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.display_name, "小明")
        self.assertEqual(await User.objects.aget_by_natural_key(" ALICE "), user)
        with self.assertRaises(User.DoesNotExist):
            await User.objects.aget_by_natural_key("非法用户名")

    async def test_async_ordinary_creation_cannot_grant_maintenance_flags(self):
        with self.assertRaises(ValueError):
            await User.objects.acreate_user("student01", password=None, is_superuser=True)
        self.assertEqual(await User.objects.acount(), 0)


class ClassRelationshipTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("student01", password=None)
        self.a = Classroom.objects.create(code="class-a", name="甲班")
        self.b = Classroom.objects.create(code="class-b", name="乙班")

    def test_unassigned_student_is_valid(self):
        self.assertFalse(StudentEnrollment.objects.filter(student=self.user).exists())
        self.assertTrue(self.user.is_active)

    def test_student_cannot_have_two_current_classes(self):
        StudentEnrollment.objects.create(student=self.user, classroom=self.a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentEnrollment.objects.create(student=self.user, classroom=self.b)

    def test_teacher_can_have_two_classes_but_no_duplicate_grant(self):
        TeacherClassGrant.objects.create(teacher=self.user, classroom=self.a)
        TeacherClassGrant.objects.create(teacher=self.user, classroom=self.b)
        self.assertEqual(self.user.class_grants.count(), 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeacherClassGrant.objects.create(teacher=self.user, classroom=self.a)
        self.assertFalse(self.user.is_staff)
        self.assertEqual(self.user.groups.count(), 0)

    def test_relationships_protect_user_and_class_from_accidental_delete(self):
        StudentEnrollment.objects.create(student=self.user, classroom=self.a)
        with self.assertRaises(ProtectedError):
            self.user.delete()
        with self.assertRaises(ProtectedError):
            self.a.delete()

    def test_class_code_is_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Classroom.objects.create(code="class-a", name="另一个班")

    def test_blank_or_control_character_class_fields_are_rejected(self):
        for code, name in [("   ", "甲班"), ("class-c", "   "), ("class-c", "甲\n班")]:
            with self.subTest(code=code, name=name), transaction.atomic(), self.assertRaises(ValidationError):
                Classroom.objects.create(code=code, name=name)

    def test_class_fields_are_trimmed_before_uniqueness_check(self):
        classroom = Classroom.objects.create(code=" class-c ", name=" 丙班 ")
        self.assertEqual(classroom.code, "class-c")
        self.assertEqual(classroom.name, "丙班")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Classroom.objects.create(code="class-c", name="另一个班")


class RoleInitializationTests(TestCase):
    def test_role_initialization_is_idempotent_and_does_not_grant_users(self):
        user = User.objects.create_user("student01", password=None)
        for _ in range(2):
            call_command("init_roles", stdout=StringIO())
        self.assertEqual(Group.objects.filter(name__in=[STUDENT, TEACHER, MAINTAINER]).count(), 3)
        self.assertEqual(User.objects.count(), 1)
        user.refresh_from_db()
        self.assertEqual(user.groups.count(), 0)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_maintainer_and_teacher_permissions_are_separate(self):
        call_command("init_roles", stdout=StringIO())
        teacher = Group.objects.get(name=TEACHER)
        maintainer = Group.objects.get(name=MAINTAINER)
        self.assertSetEqual(set(teacher.permissions.values_list("codename", flat=True)), {"view_class_progress", "export_class_scores", "export_class_roster"})
        self.assertSetEqual(set(maintainer.permissions.values_list("codename", flat=True)), {"maintain_accounts", "maintain_class_assignments"})
        self.assertFalse(Group.objects.get(name=STUDENT).permissions.exists())

    def test_rerun_repairs_reserved_group_permissions_without_removing_members(self):
        call_command("init_roles", stdout=StringIO())
        teacher = Group.objects.get(name=TEACHER)
        user = User.objects.create_user("teacher01", password=None)
        user.groups.add(teacher)
        teacher.permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="change_user"))
        call_command("init_roles", stdout=StringIO())
        self.assertFalse(teacher.permissions.filter(codename="change_user").exists())
        self.assertTrue(user.groups.filter(name=TEACHER).exists())


class ConcurrentUsernameTests(TransactionTestCase):
    def test_simultaneous_equivalent_usernames_only_create_one_account(self):
        barrier = Barrier(2)

        def create(username):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    with transaction.atomic():
                        User.objects.create_user(username, password=None)
                    return "created"
                except IntegrityError:
                    return "duplicate"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, ["Student01", " student01 "]))
        self.assertCountEqual(results, ["created", "duplicate"])
        self.assertEqual(User.objects.filter(username="student01").count(), 1)
