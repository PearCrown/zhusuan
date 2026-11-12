"""电路工坊的接口契约。

这些用例存在的理由：电路编辑器此前没有任何测试覆盖，于是三个缺陷同时潜伏
而无人知晓——连线因为字段名不一致永远画不出来、模拟因为去列表里找真值表而
必崩、提交因为没有 CSRF token 而被中间件直接挡回。页面就这样坏了很久。

下面的用例把「编辑器依赖后端提供什么」和「提交必须是什么形状」钉死，
再改动这块代码时，坏掉会在 6 秒内暴露。
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase

from accounts.roles import STUDENT

User = get_user_model()
PASSWORD = "Bamboo!River-7429-Cloud"

PAGE = "/game/circuit"
LIST = "/game/api/circuit/puzzles"
DETAIL = "/game/api/circuit/puzzles/tc-nand"
GRADE = "/game/api/circuit/puzzles/tc-nand/grade"


def nand_circuit():
    """用一个 NAND 门完成第一关：A、B 各接一个输入端口，输出接 Y。"""
    gates = [{"id": "g1", "type": "NAND", "x": 300, "y": 220}]
    wires = [
        {"from": {"gateId": "__in_A", "port": "out"}, "to": {"gateId": "g1", "port": "in1"}},
        {"from": {"gateId": "__in_B", "port": "out"}, "to": {"gateId": "g1", "port": "in2"}},
        {"from": {"gateId": "g1", "port": "out"}, "to": {"gateId": "__out_Y", "port": "in1"}},
    ]
    return gates, wires


class CircuitPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.alice = User.objects.create_user("alice01", display_name="小明", password=PASSWORD)
        cls.alice.groups.add(Group.objects.get(name=STUDENT))

    def test_page_requires_login(self):
        response = self.client.get(PAGE)
        self.assertEqual(response.status_code, 302)

    def test_page_renders_the_canvas_for_a_student(self):
        self.client.force_login(self.alice)
        response = self.client.get(PAGE)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="circuit-canvas"')
        self.assertContains(response, "/static/js/circuit.js")

    def test_page_loads_the_chapter_client(self):
        """页面必须加载章节 SDK 并带齐进度元素，否则存档与成绩回传会静默失效。"""
        self.client.force_login(self.alice)
        response = self.client.get(PAGE)
        self.assertContains(response, "/static/js/chapter-sdk.js")
        self.assertContains(response, 'id="btn-settle"')
        self.assertContains(response, 'id="chapter-status"')
        # 页面必须有常驻的返回入口，不能只靠品牌名当链接。
        self.assertContains(response, 'id="back-home"')
        self.assertContains(response, '返回主页')

    def test_workshop_entry_is_intentionally_removed(self):
        """用户 2026-11-09 要求先摘掉工坊入口，所以账号中心与场景页都不再链出。

        页面本身还在：/game/circuit 直开可用，关卡也仍从这里进（/game/level/<id>）。
        要恢复入口，反向执行提交 1a0cdb6 即可。
        """
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/game/circuit"')
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get("/game/"), 'href="/game/circuit"')
        self.assertEqual(self.client.get("/game/circuit").status_code, 200)
        self.assertEqual(self.client.get("/game/level/tc-nand").status_code, 200)

    def test_unreleased_level_page_is_404_for_a_logged_in_student(self):
        """已登录的学生也不能直开未发布关卡页——否则演示里会留一个没分的死入口。"""
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get("/game/level/tc-nand").status_code, 200)
        self.assertEqual(self.client.get("/game/level/tc-and").status_code, 404)


class CircuitPuzzleApiTests(TestCase):
    def test_list_returns_summary_fields_only(self):
        body = self.client.get(LIST).json()
        self.assertTrue(body["ok"])
        puzzles = body["data"]["puzzles"]
        self.assertTrue(puzzles)
        self.assertEqual(set(puzzles[0]), {"id", "title", "description"})

    def test_unreleased_puzzle_is_not_reachable_by_id(self):
        """未发布的关卡：列表里没有，按 id 直开详情也必须是 404。"""
        body = self.client.get(LIST).json()["data"]["puzzles"]
        self.assertEqual([p["id"] for p in body], ["tc-nand"])
        response = self.client.get("/game/api/circuit/puzzles/tc-and")
        self.assertEqual(response.status_code, 404, response.content)
        # 关卡页要求登录（匿名是 302），未登录下断言 404 没有意义，这里只验接口。

    def test_detail_carries_everything_the_editor_needs(self):
        """列表只有摘要，所以编辑器必须能从详情里取到真值表与组件表。"""
        puzzle = self.client.get(DETAIL).json()["data"]["puzzle"]
        for key in ("title", "description", "components", "inputs", "outputs", "truthTable"):
            self.assertIn(key, puzzle)
        self.assertEqual(len(puzzle["truthTable"]), 4)
        self.assertEqual(set(puzzle["truthTable"][0]), {"inputs", "outputs"})
        self.assertEqual(puzzle["id"], "tc-nand")  # 详情必须自带 id，否则前端提交会漏字段
        self.assertEqual(puzzle["inputs"], ["A", "B"])
        self.assertEqual(puzzle["outputs"], ["Y"])

    def test_unknown_puzzle_is_a_json_404(self):
        response = self.client.get("/game/api/circuit/puzzles/nope")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["ok"])


class CircuitGradeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.alice = User.objects.create_user("alice01", display_name="小明", password=PASSWORD)
        cls.alice.groups.add(Group.objects.get(name=STUDENT))

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.alice)
        self.token = self.client.get("/auth/csrf").json()["data"]["csrfToken"]

    def post(self, payload, token=None):
        return self.client.post(
            GRADE,
            data=payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.token if token is None else token,
        )

    def test_submission_without_a_csrf_token_is_rejected(self):
        response = self.post({"gates": [], "wires": []}, token="")
        self.assertEqual(response.status_code, 403)

    def test_anonymous_submission_is_rejected(self):
        # 登出会轮换 CSRF token，所以匿名请求要用独立客户端各取一次。
        anonymous = Client(enforce_csrf_checks=True)
        token = anonymous.get("/auth/csrf").json()["data"]["csrfToken"]
        response = anonymous.post(
            GRADE,
            data={"gates": [], "wires": []},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 401)

    def test_correct_nand_circuit_passes(self):
        gates, wires = nand_circuit()
        body = self.post({"gates": gates, "wires": wires}).json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["data"]["passed"])
        self.assertEqual(body["data"]["points"], 100)
        self.assertEqual(len(body["data"]["cases"]), 4)

    def test_empty_circuit_fails_and_reports_which_rows_mismatch(self):
        body = self.post({"gates": [], "wires": []}).json()
        self.assertFalse(body["data"]["passed"])
        self.assertEqual(body["data"]["points"], 0)
        # 空白电路输出恒为 0，只有「A=1,B=1 → Y=0」那一行恰好对上。
        self.assertEqual([case["pass"] for case in body["data"]["cases"]], [False, False, False, True])
