from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import StringIO
import csv
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import connections, DatabaseError, IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from accounts.models import User
from classrooms.models import Classroom, StudentEnrollment, TeacherClassGrant
from gameplay.chapters import REGISTRY, get_chapter, register, Chapter
from gameplay.models import ChapterProgress
from gameplay.question_bank import RELEASES, Question, register_release

CHAPTER = "sample-counting"
PATH = f"/game/api/chapters/{CHAPTER}"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class GameTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.student = User.objects.create_user("game_student", display_name="演示同学", password="River!Cloud-7268")
        cls.other = User.objects.create_user("game_other", password="River!Cloud-7268")
        cls.teacher = User.objects.create_user("game_teacher", password="River!Cloud-7268")
        cls.maintainer = User.objects.create_user("game_maintainer", password="River!Cloud-7268")
        cls.teacher.groups.add(Group.objects.get(name="teacher"))
        cls.maintainer.groups.add(Group.objects.get(name="maintainer"))
        cls.a = Classroom.objects.create(code="GAME-A", name="游戏一班")
        cls.b = Classroom.objects.create(code="GAME-B", name="游戏二班")
        StudentEnrollment.objects.create(student=cls.student, classroom=cls.a)
        TeacherClassGrant.objects.create(teacher=cls.teacher, classroom=cls.a)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.student)
        self.data = self.load()

    def load(self, client=None):
        return (client or self.client).get(PATH + "/progress").json()["data"]

    def act(self, action, fields=None, *, data=None, client=None):
        client = client or self.client
        data = data or self.data
        csrf = client.get("/auth/csrf").json()["data"]["csrfToken"]
        response = client.post(PATH + "/action", {"action": action, "revision": data["progress"]["revision"], "saveContext": data["saveContext"], **(fields or {})}, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        if response.status_code == 200 and client is self.client:
            self.data = response.json()["data"]
        return response

    def prepare(self):
        for action, fields in [("talk", {}), ("accept", {}), ("move", {"scene": "workshop"}), ("answer", {"questionIndex": 0, "answer": 5}), ("answer", {"questionIndex": 1, "answer": 12}), ("answer", {"questionIndex": 2, "answer": 13}), ("move", {"scene": "gate"})]:
            self.assertEqual(self.act(action, fields).status_code, 200)

    def scores(self, classroom=None, csv=False):
        return f"/game/api/teacher/classes/{(classroom or self.a).pk}/scores{'.csv' if csv else ''}"

    def test_reads_do_not_create_saves_and_answers_are_not_in_question_data(self):
        self.assertFalse(ChapterProgress.objects.exists())
        self.assertEqual(self.data["progress"]["revision"], 0)
        self.assertEqual(self.data["questions"][0], {"questionId": "sum-2-3", "prompt": "2 + 3 = ?"})
        self.assertNotIn("answer", self.data["questions"][0])
        self.assertIn("story", self.data["progress"]["state"])
        self.assertIn("practice", self.data["progress"]["state"])

    def test_play_submit_score_and_restore_are_persisted(self):
        self.prepare()
        response = self.act("submit")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data["progress"]["result"]["score"], 100)
        row = ChapterProgress.objects.get()
        self.assertEqual(row.submission_class, self.a)
        self.assertEqual(self.load()["progress"], self.data["progress"])

    def test_wrong_answers_are_graded_by_server(self):
        self.prepare()
        self.act("move", {"scene": "workshop"})
        self.act("answer", {"questionIndex": 2, "answer": 0})
        self.act("move", {"scene": "gate"})
        self.act("submit")
        self.assertEqual(ChapterProgress.objects.get().score, 60)

    def test_duplicate_submit_returns_original_result_without_new_revision(self):
        self.prepare()
        before = self.data
        self.act("submit")
        result = self.data["progress"]
        self.assertEqual(self.act("submit", data=before).json()["data"]["progress"], result)
        self.assertEqual(ChapterProgress.objects.count(), 1)
        self.assertEqual(self.act("move", {"scene": "workshop"}).status_code, 409)

    def test_illegal_task_order_and_incomplete_submit_rejected(self):
        for action, fields in [("accept", {}), ("submit", {}), ("answer", {"questionIndex": 0, "answer": 5})]:
            self.assertEqual(self.act(action, fields).status_code, 409)
        self.assertFalse(ChapterProgress.objects.exists())

    def test_stale_revision_and_forged_fields_do_not_overwrite(self):
        stale = self.data
        self.act("talk")
        self.assertEqual(self.act("accept", data=stale).status_code, 409)
        for key, value in [("score", 100), ("userId", str(self.other.pk)), ("classId", str(self.b.pk)), ("role", "teacher"), ("state", {})]:
            self.assertEqual(self.act("talk", {key: value}).status_code, 400)
        self.assertEqual(ChapterProgress.objects.get().revision, 1)

    def test_account_switch_and_same_account_relogin_reject_old_context(self):
        old = self.data
        self.client.force_login(self.other)
        self.assertEqual(self.act("talk", data=old).status_code, 409)
        self.assertFalse(ChapterProgress.objects.exists())
        # Actual login rotates the session, unlike force_login's same-user path.
        csrf = self.client.get("/auth/csrf").json()["data"]["csrfToken"]
        self.client.post("/auth/login", {"username": self.student.username, "password": "River!Cloud-7268"}, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(self.act("talk", data=old).status_code, 409)

    def test_saved_progress_is_separate_for_each_user(self):
        self.act("talk")
        self.client.force_login(self.other)
        data = self.load()
        self.assertEqual(data["progress"]["revision"], 0)
        self.assertFalse(data["progress"]["state"]["story"]["talkedToNpc"])

    def test_csrf_method_media_and_anonymous_checks(self):
        self.assertEqual(Client().get(PATH + "/progress").status_code, 401)
        self.assertEqual(self.client.get(PATH + "/action").status_code, 405)
        self.assertEqual(self.client.post(PATH + "/progress", "bad", content_type="application/x-www-form-urlencoded").status_code, 405)
        self.assertEqual(self.client.post(PATH + "/action", {}, content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(PATH + "/action", "bad", content_type="text/plain").status_code, 415)
        self.assertEqual(self.client.get("/game/api/chapters/unknown/progress").status_code, 404)
        self.assertEqual(self.client.get(PATH + "/progress?userId=other").status_code, 400)

    def test_boolean_revision_and_answers_not_coerced(self):
        self.assertEqual(self.act("talk", {"revision": True}).status_code, 400)
        self.assertEqual(self.act("move", {"scene": []}).status_code, 400)
        self.prepare()
        self.act("move", {"scene": "workshop"})
        for answer in [True, "5", 5.2, -1, 10001]:
            self.assertEqual(self.act("answer", {"questionIndex": 0, "answer": answer}).status_code, 400)

    def test_database_failure_rolls_back_save(self):
        with patch("gameplay.models.ChapterProgress.save", side_effect=DatabaseError("hidden-secret")):
            with self.assertLogs("gameplay.views", level="ERROR") as logs:
                response = self.act("talk")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(ChapterProgress.objects.exists())
        self.assertNotIn("hidden-secret", str(logs.output) + response.content.decode())

    def test_plugin_grade_failure_cannot_mark_submitted(self):
        self.prepare()
        with patch.dict(REGISTRY, {CHAPTER: replace(get_chapter(CHAPTER), grade=lambda state: 101)}):
            with self.assertLogs("gameplay.views", level="ERROR"):
                self.assertEqual(self.act("submit").status_code, 500)
        row = ChapterProgress.objects.get()
        self.assertIsNone(row.submitted_at)
        self.assertEqual(row.state["story"]["quest"], "accepted")

    def test_schema_mismatch_is_not_silently_reset(self):
        self.act("talk")
        ChapterProgress.objects.update(schema_version=99)
        self.assertEqual(self.client.get(PATH + "/progress").status_code, 409)
        self.assertEqual(self.act("accept").status_code, 409)
        self.assertEqual(ChapterProgress.objects.get().schema_version, 99)

    def test_question_update_keeps_old_saves_and_scores_pinned(self):
        original = get_chapter(CHAPTER)
        with patch.dict(RELEASES):
            register_release("sample-arithmetic", "2", [Question("new", "8 + 8 = ?", 16, 100)])
            self.act("talk") # Establish v1 save.
            with patch.dict(REGISTRY, {CHAPTER: replace(original, question_bank_version="2")}):
                self.assertEqual(len(self.load()["questions"]), 3)
                self.prepare_after_talk()
                self.act("submit")
                self.assertEqual(ChapterProgress.objects.get().score, 100)
                self.assertEqual(ChapterProgress.objects.get().question_bank_version, "1")
                other = Client(enforce_csrf_checks=True); other.force_login(self.other)
                new_data = self.load(other)
                self.assertEqual(new_data["questions"], [{"questionId": "new", "prompt": "8 + 8 = ?"}])
                self.assertEqual(new_data["progress"]["state"]["practice"]["answers"], [None])

    def prepare_after_talk(self):
        for action, fields in [("accept", {}), ("move", {"scene": "workshop"}), ("answer", {"questionIndex": 0, "answer": 5}), ("answer", {"questionIndex": 1, "answer": 12}), ("answer", {"questionIndex": 2, "answer": 13}), ("move", {"scene": "gate"})]:
            self.assertEqual(self.act(action, fields).status_code, 200)

    def test_unsaved_old_question_page_cannot_start_new_version_by_mistake(self):
        original = get_chapter(CHAPTER)
        with patch.dict(RELEASES):
            register_release("sample-arithmetic", "2", [Question("new", "8 + 8 = ?", 16, 100)])
            with patch.dict(REGISTRY, {CHAPTER: replace(original, question_bank_version="2")}):
                self.assertEqual(self.act("talk").status_code, 409)
        self.assertFalse(ChapterProgress.objects.exists())

    def test_non_scoring_story_plugin_can_complete_without_practice(self):
        chapter = Chapter("story-only", "剧情插件测试", 1, lambda *_: {"done": False}, lambda state, action, payload: {"done": True}, None, {"submit": set()})
        with patch.dict(REGISTRY, {chapter.id: chapter}):
            data = self.client.get("/game/api/chapters/story-only/progress").json()["data"]
            csrf = self.client.get("/auth/csrf").json()["data"]["csrfToken"]
            response = self.client.post("/game/api/chapters/story-only/action", {"action": "submit", "revision": 0, "saveContext": data["saveContext"]}, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["data"]["progress"]["result"]["score"])

    def test_unassigned_score_stays_personal_and_transfer_keeps_original_class(self):
        self.prepare(); self.act("submit")
        StudentEnrollment.objects.filter(student=self.student).update(classroom=self.b)
        self.assertEqual(ChapterProgress.objects.get().submission_class_id, self.a.pk)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.scores()).json()["data"]["total"], 1)
        self.assertEqual(self.client.get(self.scores(self.b)).status_code, 404)

    def test_teacher_scope_revocation_and_export_permission(self):
        self.prepare(); self.act("submit")
        for person in [self.student, self.maintainer]:
            self.client.force_login(person)
            for path in [self.scores(), self.scores(csv=True)]:
                self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.scores()).json()["data"]["items"][0]["score"], 100)
        self.assertEqual(self.client.get(self.scores(csv=True)).status_code, 200)
        self.assertEqual(self.client.get(self.scores(self.b, csv=True)).status_code, 404)
        permission = Permission.objects.get(codename="export_class_scores")
        Group.objects.get(name="teacher").permissions.remove(permission)
        self.assertEqual(self.client.get(self.scores(csv=True)).status_code, 403)
        TeacherClassGrant.objects.filter(teacher=self.teacher).delete()
        self.assertEqual(self.client.get(self.scores()).status_code, 404)

    def test_score_csv_formula_and_no_hidden_answers(self):
        self.student.display_name = "=SUM(1,2)"; self.student.save()
        self.prepare(); self.act("submit"); self.client.force_login(self.teacher)
        response = self.client.get(self.scores(csv=True))
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[1][2], "'=SUM(1,2)")
        self.assertEqual(rows[1][-2:], ["sample-arithmetic", "1"])
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn("answers", self.client.get(self.scores()).content.decode())

    def test_unassigned_personal_result_does_not_appear_in_class_after_later_assignment(self):
        StudentEnrollment.objects.filter(student=self.student).delete()
        self.prepare(); self.act("submit")
        self.assertIsNone(ChapterProgress.objects.get().submission_class_id)
        StudentEnrollment.objects.create(student=self.student, classroom=self.a)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.scores()).json()["data"]["total"], 0)

    def test_teacher_export_failure_and_size_limit_are_json_not_partial_files(self):
        self.prepare(); self.act("submit"); self.client.force_login(self.teacher)
        with patch("gameplay.views.MAX_EXPORT_ROWS", 0):
            response = self.client.get(self.scores(csv=True))
        self.assertEqual(response.status_code, 413)
        self.assertNotIn("Content-Disposition", response)
        with patch("gameplay.views.class_scores", side_effect=DatabaseError("secret")):
            with self.assertLogs("gameplay.views", level="ERROR"):
                response = self.client.get(self.scores(csv=True))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.content.decode())

    def test_teacher_routes_recheck_anonymous_head_query_and_methods(self):
        for path in [self.scores(), self.scores(csv=True)]:
            self.assertEqual(Client().get(path).status_code, 401)
            self.assertEqual(self.client.post(path, "bad", content_type="text/plain").status_code, 405)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.head(self.scores()).status_code, 200)
        self.assertEqual(self.client.head(self.scores(csv=True)).content, b"")
        self.assertEqual(self.client.get(self.scores()+"?userId=other").status_code, 400)
        self.assertEqual(self.client.get(self.scores(csv=True)+"?page=1").status_code, 400)
        self.a.is_active=False; self.a.save()
        self.assertEqual(self.client.get(self.scores()).status_code, 404)
        self.assertEqual(self.client.get(self.scores(csv=True)).status_code, 404)

    def test_game_action_rate_limit_is_enforced(self):
        with patch("accounts.rate_limits.time.time", return_value=1000000):
            for _ in range(120):
                self.assertEqual(self.act("talk").status_code, 200)
            self.assertEqual(self.act("talk").status_code, 429)

    def test_registry_duplicate_and_bank_immutability(self):
        with self.assertRaises(ValueError): register(get_chapter(CHAPTER))
        with self.assertRaises(ValueError): register_release("sample-arithmetic", "1", [])

    def test_database_rejects_duplicate_and_invalid_score_record(self):
        self.act("talk")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChapterProgress.objects.create(user=self.student, chapter_id=CHAPTER)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChapterProgress.objects.filter(user=self.student).update(score=101, submitted_at=timezone.now())


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SaveConcurrencyTests(TransactionTestCase):
    def test_parallel_first_action_serializes_and_creates_one_record(self):
        user = User.objects.create_user("game_race")
        clients = [Client(enforce_csrf_checks=True), Client(enforce_csrf_checks=True)]
        payloads = []
        for client in clients:
            client.force_login(user)
            context = client.get(PATH + "/progress").json()["data"]["saveContext"]
            token = client.get("/auth/csrf").json()["data"]["csrfToken"]
            payloads.append((client, context, token))
        def work(args):
            client, context, token = args
            connections.close_all()
            try:
                return client.post(PATH + "/action", {"action": "talk", "revision": 0, "saveContext": context}, content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(work, payloads)), [200, 409])
        self.assertEqual(ChapterProgress.objects.count(), 1)
        self.assertEqual(ChapterProgress.objects.get().revision, 1)
