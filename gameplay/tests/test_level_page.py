"""关卡页（/game/level/<levelId>）。

剧情演完的「前往关卡」落在这里。关卡本体就是电路工坊，所以这个页面复用
circuit.html，只多传一个「从哪一关进来」。测试重点是：指定哪关就开哪关、
不认识的关卡不会白屏、以及不指定时行为与 /game/circuit 完全一致。
"""

from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from accounts.models import User

LEVELS = ("tc-nand", "tc-and", "tc-or", "tc-xor", "tc-half-adder")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LevelPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.student = User.objects.create_user("level_student", password="River!Cloud-7268")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.student)

    def page(self, level_id):
        return self.client.get(f"/game/level/{level_id}").content.decode()

    def test_anonymous_is_redirected_to_login(self):
        self.assertEqual(Client().get("/game/level/tc-nand").status_code, 302)

    def test_every_registered_puzzle_has_a_level_page(self):
        # 发布清单里的每一关都要有关卡页；未发布的谜题已下线，不在这个断言范围内。
        from gameplay.question_bank import list_circuit_puzzles
        for level_id in [p["id"] for p in list_circuit_puzzles()]:
            html = self.page(level_id)
            self.assertIn(f'data-initial-puzzle="{level_id}"', html, f"{level_id} 没有正确落到关卡页")

    def test_level_page_reuses_the_workshop(self):
        html = self.page("tc-nand")
        for element_id in ("puzzle-select", "circuit-canvas", "gates-layer", "chapter-status"):
            self.assertIn(f'id="{element_id}"', html, f"关卡页缺少工坊元素 {element_id}")

    def test_level_return_is_scoped_to_the_camp_or_hub(self):
        for query, target in (("", "/game/#stage-select"), ("?from=camp", "/game/#camp"),
                              ("?from=//example.com", "/game/#stage-select")):
            html = self.page(f"tc-nand{query}")
            self.assertIn(f'data-return-url="{target}"', html)
            self.assertIn(f'href="{target}" id="back-camp"', html)

    def test_unknown_level_is_404(self):
        self.assertEqual(self.client.get("/game/level/tc-nope").status_code, 404)

    def test_plain_circuit_page_still_starts_without_a_preset(self):
        html = self.client.get("/game/circuit").content.decode()
        self.assertIn('data-initial-puzzle=""', html)

    def test_level_ids_are_not_injectable(self):
        # 关卡 id 会原样进入 HTML 属性，这里确认带特殊字符的 id 走 404 而不是被渲染。
        for hostile in ('x"onload="alert(1)', "<script>", "tc-nand;DROP"):
            self.assertEqual(self.client.get(f"/game/level/{hostile}").status_code, 404)

    def test_post_is_refused(self):
        self.assertEqual(self.client.post("/game/level/tc-nand").status_code, 403)
