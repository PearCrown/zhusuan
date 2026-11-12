"""云端存档页：把服务端存档摊开给学生看，且只看得到自己的。"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from gameplay.models import ChapterProgress

User = get_user_model()
PASSWORD = "TestPassword-12345"
PAGE = "/game/saves"


class SavesPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("saver01", display_name="存档甲", password=PASSWORD)
        cls.bob = User.objects.create_user("saver02", display_name="存档乙", password=PASSWORD)

    def test_requires_login(self):
        self.assertEqual(self.client.get(PAGE).status_code, 302)

    def test_lists_every_registered_chapter(self):
        self.client.force_login(self.alice)
        html = self.client.get(PAGE).content.decode()
        for title in ("算坊初试", "电路工坊", "铸言", "夏社"):
            self.assertIn(title, html, title)

    def test_new_student_sees_no_saves(self):
        self.client.force_login(self.alice)
        html = self.client.get(PAGE).content.decode()
        self.assertIn("未开始", html)
        self.assertIn("还没有存档", html)

    def test_code_source_is_shown_as_the_archive(self):
        ChapterProgress.objects.create(
            user=self.alice, chapter_id="xia-code", schema_version=1,
            state={"code": {"source": "not (a and b)", "passed": True, "points": 100, "attempts": 1, "rows": []}},
            revision=2, score=100, submitted_at="2026-11-10T10:00:00+08:00",
        )
        self.client.force_login(self.alice)
        html = self.client.get(PAGE).content.decode()
        self.assertIn("not (a and b)", html, "代码存档应能看到写过的代码")
        self.assertIn("已结算", html)

    def test_circuit_summary_counts_passed_levels(self):
        ChapterProgress.objects.create(
            user=self.alice, chapter_id="xia-circuit", schema_version=1,
            state={"circuit": {"levels": {"tc-nand": {"passed": True, "points": 100, "attempts": 2}},
                               "puzzleIds": ["tc-nand"], "attempts": [{"n": 1}, {"n": 2}]}},
            revision=3, score=100, submitted_at="2026-11-10T10:00:00+08:00",
        )
        self.client.force_login(self.alice)
        html = self.client.get(PAGE).content.decode()
        self.assertIn("已通 1 / 1 关", html)
        self.assertIn("结算尝试 2 次", html)

    def test_other_students_saves_are_not_visible(self):
        ChapterProgress.objects.create(
            user=self.bob, chapter_id="xia-code", schema_version=1,
            state={"code": {"source": "bob-secret-expression", "passed": True, "points": 100, "attempts": 1, "rows": []}},
            revision=2, score=100, submitted_at="2026-11-10T10:00:00+08:00",
        )
        self.client.force_login(self.alice)
        html = self.client.get(PAGE).content.decode()
        self.assertNotIn("bob-secret-expression", html)
