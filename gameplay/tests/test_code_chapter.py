"""代码题章节（铸言）：判分、存档、防注入。

判分不执行用户代码，只遍历一棵白名单表达式树；这里重点测"什么都写不进去"。
"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from gameplay import code_chapter

User = get_user_model()
PASSWORD = "TestPassword-12345"
PAGE = "/game/code"
API = "/game/api/chapters/xia-code"


class JudgeTests(TestCase):
    def test_nand_expression_passes(self):
        result = code_chapter.judge("not (a and b)")
        self.assertTrue(result["passed"])
        self.assertEqual([row["actual"] for row in result["rows"]], [1, 1, 1, 0])

    def test_equivalent_forms_pass(self):
        for source in ("not a or not b", "(not (a and b))", "not (a and b) and True"):
            self.assertTrue(code_chapter.judge(source)["passed"], source)

    def test_and_gate_fails(self):
        result = code_chapter.judge("a and b")
        self.assertFalse(result["passed"])
        # 与非门的期望是 1,1,1,0；与门给出 0,0,0,1，四行全错。
        self.assertEqual([row["pass"] for row in result["rows"]], [False, False, False, False])

    def test_syntax_error_is_reported(self):
        with self.assertRaises(code_chapter.ApiError) as ctx:
            code_chapter.judge("not (a and")
        self.assertEqual(ctx.exception.code, "syntax_error")

    def test_empty_source_is_rejected(self):
        with self.assertRaises(code_chapter.ApiError) as ctx:
            code_chapter.judge("   ")
        self.assertEqual(ctx.exception.code, "validation_error")

    def test_only_names_operators_and_parens_are_allowed(self):
        blocked = [
            "__import__('os').system('id')",
            "a.__class__",
            "(lambda: 1)()",
            "open('x','w')",
            "a if a else b",
            "[x for x in (1,2)]",
            "a = b",
            "print(a)",
            "'text'",
            "a and b or 1 + 1",
        ]
        for source in blocked:
            with self.assertRaises(code_chapter.ApiError, msg=source) as ctx:
                code_chapter.judge(source)
            self.assertIn(ctx.exception.code, {"forbidden_node", "syntax_error", "unknown_name"}, source)

    def test_unknown_variable_is_named(self):
        with self.assertRaises(code_chapter.ApiError) as ctx:
            code_chapter.judge("a and c")
        self.assertEqual(ctx.exception.code, "unknown_name")


class CodeChapterFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("coder01", display_name="写码同学", password=PASSWORD)

    def setUp(self):
        self.client.force_login(self.alice)

    def load(self):
        return self.client.get(f"{API}/progress").json()["data"]

    def act(self, action, **fields):
        data = self.load()
        return self.client.post(
            f"{API}/action",
            {"action": action, "revision": data["progress"]["revision"],
             "saveContext": data["saveContext"], **fields},
            content_type="application/json",
        )

    def test_page_requires_login_and_renders(self):
        self.client.logout()
        self.assertEqual(self.client.get(PAGE).status_code, 302)
        self.client.force_login(self.alice)
        html = self.client.get(PAGE).content.decode()
        self.assertIn("铸言", html)
        self.assertIn('id="code-source"', html)

    def test_solving_stores_source_and_marks_passed(self):
        response = self.act("solve", source="not (a and b)")
        self.assertEqual(response.status_code, 200, response.content)
        code = response.json()["data"]["progress"]["state"]["code"]
        self.assertTrue(code["passed"])
        self.assertEqual(code["source"], "not (a and b)", "源码就是代码存档，必须原样保留")
        self.assertEqual(code["points"], 100)

    def test_wrong_expression_keeps_attempts_but_does_not_pass(self):
        response = self.act("solve", source="a and b")
        code = response.json()["data"]["progress"]["state"]["code"]
        self.assertFalse(code["passed"])
        self.assertEqual(code["attempts"], 1)
        self.assertEqual(code["source"], "a and b")

    def test_submit_without_passing_is_refused(self):
        self.act("solve", source="a and b")
        response = self.act("submit")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "invalid_transition")

    def test_submit_after_passing_records_the_score(self):
        self.act("solve", source="not (a and b)")
        response = self.act("submit")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["progress"]["result"]["score"], 100)

    def test_forbidden_code_never_reaches_the_save(self):
        before = self.load()["progress"]["state"]["code"]["source"]
        response = self.act("solve", source="__import__('os').system('id')")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "forbidden_node")
        self.assertEqual(self.load()["progress"]["state"]["code"]["source"], before)
