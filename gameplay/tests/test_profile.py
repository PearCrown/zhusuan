"""战绩页的契约：数据来自存档、排行只在同班、不泄露用户名。"""
from datetime import datetime, timezone as dt_timezone

from django.test import TestCase
from django.contrib.auth import get_user_model
from classrooms.models import Classroom, StudentEnrollment
from gameplay.models import ChapterProgress

User = get_user_model()
PASSWORD = "TestPassword-12345"
URL = "/game/profile"


def circuit_state(passed=True, points=100, attempts=2, cases=None):
    return {
        "circuit": {
            "levels": {
                "tc-nand": {
                    "passed": passed,
                    "points": points if passed else 0,
                    "attempts": attempts,
                    "lastResult": {"passed": passed, "points": points,
                                   "cases": cases or [{"inputs": [0, 0], "expected": [1], "actual": [1], "pass": True}]},
                }
            },
            "puzzleIds": ["tc-nand"],
            "attempts": [{"n": i + 1, "score": points, "maxScore": 100, "passed": passed,
                          "at": "2026-11-10T10:00:00+08:00"} for i in range(attempts)],
        }
    }


class ProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice01", display_name="甲同学", password=PASSWORD)
        cls.bob = User.objects.create_user("bob01", display_name="乙同学", password=PASSWORD)
        cls.carol = User.objects.create_user("carol01", display_name="丙同学", password=PASSWORD)
        cls.room = Classroom.objects.create(code="P-1", name="一班")
        cls.other = Classroom.objects.create(code="P-2", name="二班")
        StudentEnrollment.objects.create(student=cls.alice, classroom=cls.room)
        StudentEnrollment.objects.create(student=cls.bob, classroom=cls.room)
        StudentEnrollment.objects.create(student=cls.carol, classroom=cls.other)

        # 有成绩就必须有提交时间（数据库有 CHECK 约束）。
        cls.alice_row = ChapterProgress.objects.create(
            user=cls.alice, chapter_id="xia-circuit", schema_version=1,
            state=circuit_state(points=100), revision=3, score=100,
            submission_class=cls.room,
            submitted_at=datetime(2026, 11, 10, 2, 0, tzinfo=dt_timezone.utc),
        )
        cls.bob_row = ChapterProgress.objects.create(
            user=cls.bob, chapter_id="xia-circuit", schema_version=1,
            state=circuit_state(points=80), revision=2, score=80,
            submission_class=cls.room,
            submitted_at=datetime(2026, 11, 10, 3, 0, tzinfo=dt_timezone.utc),
        )
        ChapterProgress.objects.create(
            user=cls.carol, chapter_id="xia-circuit", schema_version=1,
            state=circuit_state(points=100), revision=1, score=100,
            submission_class=cls.other,
            submitted_at=datetime(2026, 11, 10, 1, 0, tzinfo=dt_timezone.utc),
        )

    def test_requires_login(self):
        self.assertEqual(self.client.get(URL).status_code, 302)

    def test_shows_stats_passed_levels_and_achievements(self):
        self.client.force_login(self.alice)
        html = self.client.get(URL).content.decode()
        self.assertIn("战绩", html)
        self.assertIn("完成题目数", html)
        self.assertIn("1", html)                     # 通过 1 关
        self.assertIn("100", html)                   # 最高成绩
        self.assertIn("识·与非", html)               # 通过的题目
        self.assertIn("初入算坊", html)              # 成就：第一次通过
        self.assertIn("满算", html)                  # 成就：满分
        self.assertIn("入册", html)                  # 成就：已结算

    def test_leaderboard_only_contains_the_same_class(self):
        self.client.force_login(self.alice)
        html = self.client.get(URL).content.decode()
        self.assertIn("甲同学", html)
        self.assertIn("乙同学", html)
        self.assertNotIn("丙同学", html, "别的班的学生不该出现在本班排行里")

    def test_leaderboard_does_not_expose_usernames(self):
        self.client.force_login(self.alice)
        html = self.client.get(URL).content.decode()
        for name in ("alice01", "bob01"):
            self.assertNotIn(name, html, "排行只显示显示名称，不暴露用户名")

    def test_rank_and_class_size_are_reported(self):
        self.client.force_login(self.bob)
        html = self.client.get(URL).content.decode()
        # 乙同学 80 分排在甲同学 100 分之后 → 第 2 名，共 2 人
        self.assertIn("班级排名", html)
        self.assertIn("2", html)

    def test_student_without_a_class_still_sees_own_record(self):
        lonely = User.objects.create_user("lonely01", display_name="独同学", password=PASSWORD)
        ChapterProgress.objects.create(
            user=lonely, chapter_id="xia-circuit", schema_version=1,
            state=circuit_state(points=100), revision=1, score=100,
            submitted_at=datetime(2026, 11, 10, 4, 0, tzinfo=dt_timezone.utc),
        )
        self.client.force_login(lonely)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertIn("暂时没有班级排行", response.content.decode())

    def test_student_without_progress_sees_empty_state(self):
        blank = User.objects.create_user("blank01", display_name="空同学", password=PASSWORD)
        self.client.force_login(blank)
        html = self.client.get(URL).content.decode()
        self.assertIn("还没有通过任何题目", html)

    def test_code_chapter_counts_towards_stats_and_rank(self):
        ChapterProgress.objects.create(
            user=self.bob, chapter_id="xia-code", schema_version=1,
            state={"code": {"source": "not (a and b)", "passed": True, "points": 100, "attempts": 1, "rows": []}},
            revision=1, score=100, submission_class=self.room,
            submitted_at=datetime(2026, 11, 10, 12, 0, tzinfo=dt_timezone.utc),
        )
        self.client.force_login(self.bob)
        html = self.client.get(URL).content.decode()
        # 乙同学：电路 80 + 代码 100 = 180，反超甲同学的 100 → 第 1 名
        self.assertIn("铸言", html)
        self.assertIn("180", html)
        self.assertIn("完成题目数", html)
        self.assertIn("2<small> / 2</small>", html, "两章的题目都应计入完成数")
