"""电路章节的端到端契约：判分、存档、成绩回传、教师端可见。

这一组用例回答的正是老师验收时第一个会问的问题——
「别的队的关卡怎么接进你的框架？接了之后成绩能到教师端吗？」
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import Client, TestCase

from accounts.roles import STUDENT, TEACHER
from classrooms.models import Classroom, StudentEnrollment, TeacherClassGrant
from gameplay.models import ChapterProgress

User = get_user_model()
PASSWORD = "Bamboo!River-7429-Cloud"

CHAPTER = "xia-circuit"


# ---------- 各关的最小正确电路 ----------

def nand(puzzle_inputs, gate_id, a, b):
    return [
        {"from": {"gateId": a, "port": "out"}, "to": {"gateId": gate_id, "port": "in1"}},
        {"from": {"gateId": b, "port": "out"}, "to": {"gateId": gate_id, "port": "in2"}},
    ]


def circuit_nand():
    return [{"id": "g1", "type": "NAND"}], nand(None, "g1", "__in_A", "__in_B") + [
        {"from": {"gateId": "g1", "port": "out"}, "to": {"gateId": "__out_Y", "port": "in1"}},
    ]


def circuit_and():
    gates = [{"id": "g1", "type": "NAND"}, {"id": "g2", "type": "NAND"}]
    wires = nand(None, "g1", "__in_A", "__in_B") + [
        {"from": {"gateId": "g1", "port": "out"}, "to": {"gateId": "g2", "port": "in1"}},
        {"from": {"gateId": "g1", "port": "out"}, "to": {"gateId": "g2", "port": "in2"}},
        {"from": {"gateId": "g2", "port": "out"}, "to": {"gateId": "__out_Y", "port": "in1"}},
    ]
    return gates, wires


def circuit_or():
    gates = [{"id": "g1", "type": "NAND"}, {"id": "g2", "type": "NAND"}, {"id": "g3", "type": "NAND"}]
    wires = nand(None, "g1", "__in_A", "__in_A") + nand(None, "g2", "__in_B", "__in_B") + [
        {"from": {"gateId": "g1", "port": "out"}, "to": {"gateId": "g3", "port": "in1"}},
        {"from": {"gateId": "g2", "port": "out"}, "to": {"gateId": "g3", "port": "in2"}},
        {"from": {"gateId": "g3", "port": "out"}, "to": {"gateId": "__out_Y", "port": "in1"}},
    ]
    return gates, wires


def circuit_xor():
    gates = [{"id": "n1", "type": "NAND"}, {"id": "n2", "type": "NAND"},
             {"id": "n3", "type": "NAND"}, {"id": "n4", "type": "NAND"}]
    wires = nand(None, "n1", "__in_A", "__in_B") + nand(None, "n2", "__in_A", "n1") + \
        nand(None, "n3", "__in_B", "n1") + nand(None, "n4", "n2", "n3") + [
            {"from": {"gateId": "n4", "port": "out"}, "to": {"gateId": "__out_Y", "port": "in1"}},
        ]
    return gates, wires


def circuit_half_adder():
    gates = [{"id": "x1", "type": "XOR"}, {"id": "a1", "type": "AND"}]
    wires = nand(None, "x1", "__in_A", "__in_B") + nand(None, "a1", "__in_A", "__in_B") + [
        {"from": {"gateId": "x1", "port": "out"}, "to": {"gateId": "__out_SUM", "port": "in1"}},
        {"from": {"gateId": "a1", "port": "out"}, "to": {"gateId": "__out_CARRY", "port": "in1"}},
    ]
    return gates, wires


SOLUTIONS = {
    "tc-nand": circuit_nand,
    "tc-and": circuit_and,
    "tc-or": circuit_or,
    "tc-xor": circuit_xor,
    "tc-half-adder": circuit_half_adder,
}


class ChapterClientMixin:
    """登录 + 读存档 + 发动作的公共夹具。

    URL 由 `chapter_id` 决定，子类改这个属性就能测别的章节。
    """

    chapter_id = CHAPTER

    @property
    def progress_url(self):
        return f"/game/api/chapters/{self.chapter_id}/progress"

    @property
    def action_url(self):
        return f"/game/api/chapters/{self.chapter_id}/action"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.token = None

    def login(self, user):
        self.client.force_login(user)
        self.token = self.client.get("/auth/csrf").json()["data"]["csrfToken"]

    def load_progress(self):
        body = self.client.get(self.progress_url).json()
        self.assertTrue(body["ok"], body)
        return body["data"]

    def act(self, action, **fields):
        payload = {"action": action, "revision": self.revision, "saveContext": self.save_context}
        payload.update(fields)
        response = self.client.post(
            self.action_url, data=payload, content_type="application/json", HTTP_X_CSRFTOKEN=self.token
        )
        body = response.json()
        if body.get("ok"):
            data = body["data"]
            self.revision = data["progress"]["revision"]
            self.save_context = data["saveContext"]
        return response, body

    def solve(self, puzzle_id):
        gates, wires = SOLUTIONS[puzzle_id]()
        return self.act("solve", puzzleId=puzzle_id, gates=gates, wires=wires)

    def solve_all(self):
        # 本章当前只发布第一关（100 分），其余四关的定义保留但未发布。
        for puzzle_id in ("tc-nand",):
            response, body = self.solve(puzzle_id)
            self.assertEqual(response.status_code, 200, body)
            self.assertTrue(body["data"]["progress"]["state"]["circuit"]["levels"][puzzle_id]["passed"])


class CircuitChapterTests(ChapterClientMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.alice = User.objects.create_user("alice01", display_name="小明", password=PASSWORD)
        cls.alice.groups.add(Group.objects.get(name=STUDENT))

    def setUp(self):
        super().setUp()
        self.login(self.alice)
        data = self.load_progress()
        self.revision = data["progress"]["revision"]
        self.save_context = data["saveContext"]

    def test_chapter_is_listed_next_to_the_sample(self):
        body = self.client.get("/game/api/chapters").json()
        chapters = {c["chapterId"]: c for c in body["data"]["chapters"]}
        self.assertIn(CHAPTER, chapters)
        self.assertEqual(chapters[CHAPTER]["kind"], "circuit")

    def test_progress_starts_empty_and_needs_no_question_text(self):
        self.assertEqual(self.revision, 0)
        self.assertIsNone(ChapterProgress.objects.filter(user=self.alice, chapter_id=CHAPTER).first())
        body = self.client.get(self.progress_url).json()
        self.assertEqual(body["data"]["questions"], [])
        self.assertEqual(body["data"]["progress"]["state"]["circuit"]["levels"], {})

    def test_solving_a_level_saves_the_circuit_without_scoring_yet(self):
        response, body = self.solve("tc-nand")
        self.assertEqual(response.status_code, 200, body)
        progress = body["data"]["progress"]
        self.assertIsNone(progress["result"])          # 尚未结算，没有成绩
        level = progress["state"]["circuit"]["levels"]["tc-nand"]
        self.assertTrue(level["passed"])
        self.assertEqual(level["attempts"], 1)
        self.assertTrue(level["gates"])                 # 电路存档
        self.assertTrue(level["wires"])
        row = ChapterProgress.objects.get(user=self.alice, chapter_id=CHAPTER)
        self.assertIsNone(row.score)
        self.assertIsNone(row.submitted_at)

    def test_settling_without_a_passing_level_records_a_failed_attempt(self):
        """没到通过线就只留一条尝试记录：不写成绩，也不锁章节。"""
        self.act("solve", puzzleId="tc-nand", gates=[], wires=[])   # 空电路：0 分
        response, body = self.act("settle")
        self.assertEqual(response.status_code, 200, body)
        progress = body["data"]["progress"]
        self.assertIsNone(progress["result"], "未通过不该产生成绩")
        circuit = progress["state"]["circuit"]
        self.assertEqual([a["score"] for a in circuit["attempts"]], [0])
        self.assertFalse(circuit["attempts"][0]["passed"])
        self.assertFalse(circuit["pendingSettle"])
        row = ChapterProgress.objects.get(user=self.alice, chapter_id=CHAPTER)
        self.assertIsNone(row.score)
        self.assertIsNone(row.submitted_at)

    def test_failed_settlement_does_not_lock_the_chapter(self):
        """失败之后还能继续做工——这正是「失败可重试」的一半。"""
        self.act("settle")                       # 什么都没做：0 分，未通过
        response, body = self.solve("tc-nand")   # 失败之后仍能继续做工
        self.assertEqual(response.status_code, 200, body)
        self.assertTrue(body["data"]["progress"]["state"]["circuit"]["levels"]["tc-nand"]["passed"])

    def test_submit_without_a_passing_attempt_is_refused(self):
        """没通过就结算必须被拒，否则「失败可重试」变成「失败也入库」。"""
        self.solve("tc-nand")
        response, body = self.act("submit")
        self.assertEqual(response.status_code, 409, body)
        self.assertEqual(body["error"]["code"], "invalid_transition")
        self.assertFalse(ChapterProgress.objects.get(user=self.alice, chapter_id=CHAPTER).score)

    def test_retry_keeps_the_old_failed_record_and_settles_on_the_second_try(self):
        self.act("settle")                 # 第一次：一关没做，0 分，未通过
        self.solve_all()                   # 做出第一关
        _, body = self.act("settle")       # 第二次：100 分
        circuit = body["data"]["progress"]["state"]["circuit"]
        self.assertEqual([a["score"] for a in circuit["attempts"]], [0, 100])
        self.assertEqual([a["passed"] for a in circuit["attempts"]], [False, True])
        self.assertTrue(circuit["pendingSettle"])

        _, body = self.act("submit")
        progress = body["data"]["progress"]
        self.assertEqual(progress["result"]["score"], 100)
        # 结算之后，两次尝试记录都还在
        self.assertEqual([a["score"] for a in progress["state"]["circuit"]["attempts"]], [0, 100])

    def test_old_save_without_attempt_fields_keeps_playing(self):
        """老存档没有 attempts / pendingSettle：读得到、能继续，不报 409。"""
        self.solve("tc-nand")
        row = ChapterProgress.objects.get(user=self.alice, chapter_id=CHAPTER)
        state = row.state
        del state["circuit"]["attempts"]
        del state["circuit"]["pendingSettle"]
        row.state = state
        row.save(update_fields=["state"])

        body = self.client.get(self.progress_url).json()
        self.assertTrue(body["ok"], body)
        self.assertNotIn("attempts", body["data"]["progress"]["state"]["circuit"])

        response, body = self.act("settle")
        self.assertEqual(response.status_code, 200, body)
        self.assertEqual([a["score"] for a in body["data"]["progress"]["state"]["circuit"]["attempts"]], [100])

    def test_the_single_released_level_settles_at_full_marks(self):
        self.solve_all()
        response, body = self.act("settle")
        self.assertEqual(response.status_code, 200, body)
        self.assertTrue(body["data"]["progress"]["state"]["circuit"]["pendingSettle"])
        response, body = self.act("submit")
        self.assertEqual(response.status_code, 200, body)
        self.assertEqual(body["data"]["progress"]["result"]["score"], 100)

    def test_a_wrong_circuit_counts_an_attempt_but_scores_nothing(self):
        response, body = self.act("solve", puzzleId="tc-nand", gates=[], wires=[])
        self.assertEqual(response.status_code, 200, body)
        level = body["data"]["progress"]["state"]["circuit"]["levels"]["tc-nand"]
        self.assertFalse(level["passed"])
        self.assertEqual(level["attempts"], 1)
        self.assertEqual(level["points"], 0)

    def test_forbidden_component_is_refused(self):
        """「本关只准用 NAND」必须由服务端执行，否则形同虚设。"""
        gates = [{"id": "a1", "type": "AND"}]
        wires = nand(None, "a1", "__in_A", "__in_B") + [
            {"from": {"gateId": "a1", "port": "out"}, "to": {"gateId": "__out_Y", "port": "in1"}},
        ]
        response, body = self.act("solve", puzzleId="tc-nand", gates=gates, wires=wires)
        self.assertEqual(response.status_code, 400, body)
        self.assertEqual(body["error"]["code"], "invalid_component")

    def test_unknown_puzzle_is_a_404(self):
        response, body = self.act("solve", puzzleId="tc-nope", gates=[], wires=[])
        self.assertEqual(response.status_code, 404)
        self.assertEqual(body["error"]["code"], "puzzle_not_found")

    def test_malformed_circuit_is_rejected_not_graded(self):
        response, body = self.act("solve", puzzleId="tc-nand", gates="nope", wires=[])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "validation_error")

    def test_unknown_action_is_refused(self):
        response, body = self.act("grade")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "invalid_action")

    def test_settlement_is_idempotent(self):
        self.solve_all()
        self.act("settle")
        self.act("submit")
        first = ChapterProgress.objects.get(user=self.alice, chapter_id=CHAPTER)
        _, body = self.act("submit")
        self.assertEqual(body["data"]["progress"]["result"]["score"], 100)
        second = ChapterProgress.objects.get(user=self.alice, chapter_id=CHAPTER)
        self.assertEqual(first.submitted_at, second.submitted_at)
        self.assertEqual(first.revision, second.revision)

    def test_settled_chapter_can_be_replayed_without_lowering_the_score(self):
        """结算之后仍可重做：成绩取历史最高，重做不会把它改小。"""
        self.solve_all()
        self.act("settle")
        self.act("submit")
        first = ChapterProgress.objects.get(user=self.alice, chapter_id=CHAPTER)
        self.assertEqual(first.score, 100)

        # 重做一次没通过的（空电路），再结算：成绩必须还是 100。
        self.act("solve", puzzleId="tc-nand", gates=[], wires=[])
        self.act("settle")
        _, body = self.act("submit")
        self.assertEqual(body["data"]["progress"]["result"]["score"], 100, "重做不能把已记录的成绩改小")
        self.assertEqual(body["data"]["progress"]["state"]["circuit"]["pendingSettle"], False,
                         "结算完成后不该还挂着待结算")


class CircuitScoreVisibilityTests(ChapterClientMixin, TestCase):
    """学生的电路成绩必须走得到教师端（页面与 CSV）。"""

    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.teacher = User.objects.create_user("teachera", display_name="甲老师")
        cls.student = User.objects.create_user("studenta", display_name="甲同学", password=PASSWORD)
        cls.outsider = User.objects.create_user("studentb", display_name="乙同学", password=PASSWORD)
        cls.teacher.groups.add(Group.objects.get(name=TEACHER))
        cls.student.groups.add(Group.objects.get(name=STUDENT))
        cls.outsider.groups.add(Group.objects.get(name=STUDENT))
        cls.first = Classroom.objects.create(code="A01", name="一班")
        cls.second = Classroom.objects.create(code="B01", name="二班")
        TeacherClassGrant.objects.create(teacher=cls.teacher, classroom=cls.first)
        StudentEnrollment.objects.create(student=cls.student, classroom=cls.first)
        StudentEnrollment.objects.create(student=cls.outsider, classroom=cls.second)

    def grant_export(self):
        self.teacher.user_permissions.add(
            Permission.objects.get(content_type__app_label="classrooms", content_type__model="classroom", codename="export_class_scores")
        )

    def settle_full_marks(self):
        """结算一次满分：未到通过线的尝试不入库，所以这里必须全通。"""
        self.login(self.student)
        data = self.load_progress()
        self.revision = data["progress"]["revision"]
        self.save_context = data["saveContext"]
        self.solve_all()
        self.act("settle")
        self.act("submit")

    def test_teacher_scores_include_the_circuit_chapter(self):
        self.settle_full_marks()
        self.login(self.teacher)
        body = self.client.get(f"/game/api/teacher/classes/{self.first.pk}/scores").json()
        self.assertTrue(body["ok"], body)
        rows = body["data"]["items"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["chapterId"], CHAPTER)
        self.assertEqual(row["score"], 100)
        self.assertEqual(row["questionBank"]["bankId"], "circuit-levels")

    def test_csv_export_carries_the_score(self):
        self.settle_full_marks()
        self.login(self.teacher)
        self.grant_export()
        response = self.client.get(f"/game/api/teacher/classes/{self.first.pk}/scores.csv")
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        self.assertIn(CHAPTER, text)
        self.assertIn("100", text)
        self.assertNotIn(self.outsider.username, text)

    def test_unsubmitted_play_is_invisible_to_the_teacher(self):
        self.login(self.student)
        data = self.load_progress()
        self.revision = data["progress"]["revision"]
        self.save_context = data["saveContext"]
        self.solve("tc-nand")
        self.login(self.teacher)
        body = self.client.get(f"/game/api/teacher/classes/{self.first.pk}/scores").json()
        self.assertEqual(body["data"]["items"], [])
