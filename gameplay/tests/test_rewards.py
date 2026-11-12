"""奖励账本：只发一次，重玩不刷奖。

两层测试：
1. `gameplay/rewards.py` 这个纯函数账本本身的不变式——首次时间不被覆盖、
   被拒时只留痕不计数。这一层不需要数据库。
2. 走真实 HTTP 链路：同一关重玩两次，账本里的 count 仍然是 1。

第 2 层复用 `test_circuit_chapter` 的客户端夹具，因为目前唯一挂了奖励的
章节就是电路章节（关卡数据里的 `reward` 字段）。
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from accounts.roles import STUDENT
from gameplay import rewards
from gameplay.models import ChapterProgress
from gameplay.tests.test_circuit_chapter import CHAPTER, PASSWORD, ChapterClientMixin

User = get_user_model()


class LedgerTests(SimpleTestCase):
    """账本本身的不变式。"""

    def test_first_grant_records_time_and_count(self):
        state = {}
        self.assertTrue(rewards.grant(state, "side-quest-1", at="2026-11-06T10:00:00"))
        entry = rewards.entry_of(state, "side-quest-1")
        self.assertEqual(entry["count"], 1)
        self.assertEqual(entry["limit"], 1)
        self.assertEqual(entry["firstAt"], "2026-11-06T10:00:00")
        self.assertEqual(entry["lastAt"], "2026-11-06T10:00:00")
        self.assertTrue(rewards.granted(state, "side-quest-1"))

    def test_second_grant_is_refused_and_keeps_the_first_time(self):
        """重玩再领：不发，首次时间不被覆盖，只留下"又领过一次"的痕迹。"""
        state = {}
        rewards.grant(state, "side-quest-1", at="2026-11-06T10:00:00")
        self.assertFalse(rewards.grant(state, "side-quest-1", at="2026-11-06T11:30:00"))
        entry = rewards.entry_of(state, "side-quest-1")
        self.assertEqual(entry["count"], 1)
        self.assertEqual(entry["firstAt"], "2026-11-06T10:00:00")
        self.assertEqual(entry["lastAt"], "2026-11-06T10:00:00")
        self.assertEqual(entry["lastAttemptAt"], "2026-11-06T11:30:00")

    def test_limit_allows_repeatable_rewards(self):
        """limit > 1 时真的能重复发到上限——给"每日可领一次"留的路。"""
        state = {}
        self.assertTrue(rewards.grant(state, "daily", at="d1", limit=2))
        self.assertTrue(rewards.grant(state, "daily", at="d2", limit=2))
        self.assertFalse(rewards.grant(state, "daily", at="d3", limit=2))
        entry = rewards.entry_of(state, "daily")
        self.assertEqual(entry["count"], 2)
        self.assertEqual(entry["lastAt"], "d2")
        self.assertEqual(entry["lastAttemptAt"], "d3")

    def test_state_without_ledger_gets_one(self):
        """老存档没有 rewards 键：第一次发放时就地补建，不需要迁移。"""
        state = {"story": {"quest": "accepted"}}
        self.assertIsNone(rewards.entry_of(state, "side-quest-1"))
        self.assertFalse(rewards.granted(state, "side-quest-1"))
        self.assertTrue(rewards.grant(state, "side-quest-1", at="2026-11-06T10:00:00"))
        self.assertEqual(state["rewards"]["side-quest-1"]["count"], 1)

    def test_bad_reward_id_is_refused(self):
        for bad in ("", None, 7):
            with self.assertRaises(ValueError):
                rewards.grant({}, bad, at="2026-11-06T10:00:00")

    def test_bad_timestamp_is_refused(self):
        with self.assertRaises(ValueError):
            rewards.grant({}, "side-quest-1", at="")


class CircuitRewardTests(ChapterClientMixin, TestCase):
    """走 HTTP 的真实链路：同一关重玩两次，奖励只发一次。"""

    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.student = User.objects.create_user("reward_student", display_name="奖励同学", password=PASSWORD)
        cls.student.groups.add(Group.objects.get(name=STUDENT))

    def setUp(self):
        super().setUp()
        self.login(self.student)
        data = self.load_progress()
        self.revision = data["progress"]["revision"]
        self.save_context = data["saveContext"]

    def ledger_of(self, body):
        return body["data"]["progress"]["state"].get("rewards", {})

    def test_clearing_a_level_grants_its_reward_once(self):
        response, body = self.solve("tc-nand")
        self.assertEqual(response.status_code, 200, body)
        entry = self.ledger_of(body)["level-tc-nand-cleared"]
        self.assertEqual(entry["count"], 1)
        self.assertIn("firstAt", entry)

    def test_replaying_the_same_level_does_not_grant_again(self):
        """整条验收的正面场景：重玩一次，账本仍是 1，首次时间不变。"""
        self.solve("tc-nand")
        first = self.ledger_of({"data": self.load_progress()})["level-tc-nand-cleared"]

        response, body = self.solve("tc-nand")          # 重玩同一关
        self.assertEqual(response.status_code, 200, body)
        again = self.ledger_of(body)["level-tc-nand-cleared"]

        self.assertEqual(again["count"], 1, "重玩不该再发一次")
        self.assertEqual(again["firstAt"], first["firstAt"], "首次发放时间不能被覆盖")
        self.assertIn("lastAttemptAt", again, "被拒的那次应该留痕")
        level = body["data"]["progress"]["state"]["circuit"]["levels"]["tc-nand"]
        self.assertEqual(level["attempts"], 2, "关卡本身的尝试次数照常累加")

    def test_the_released_level_grants_its_reward_once(self):
        # 本章目前只发布第一关；奖励按关卡 id 各记一份，不应叠成两条。
        _, body = self.solve("tc-nand")
        book = self.ledger_of(body)
        self.assertEqual(book["level-tc-nand-cleared"]["count"], 1)
        self.assertEqual(len(book), 1)

    def test_a_wrong_circuit_grants_nothing(self):
        response, body = self.act("solve", puzzleId="tc-nand", gates=[], wires=[])
        self.assertEqual(response.status_code, 200, body)
        self.assertEqual(self.ledger_of(body), {}, "没通过就没有奖励")

    def test_ledger_survives_a_refresh(self):
        self.solve("tc-nand")
        reloaded = self.load_progress()["progress"]["state"]["rewards"]
        self.assertEqual(reloaded["level-tc-nand-cleared"]["count"], 1)

    def test_old_save_without_a_ledger_keeps_playing(self):
        """老存档没有 rewards 键：读得到、能继续，第一次发放时就地补建。"""
        self.solve("tc-nand")
        row = ChapterProgress.objects.get(user=self.student, chapter_id=CHAPTER)
        state = row.state
        del state["rewards"]
        row.state = state
        row.save(update_fields=["state"])

        body = self.client.get(f"/game/api/chapters/{CHAPTER}/progress").json()
        self.assertTrue(body["ok"], body)
        self.assertNotIn("rewards", body["data"]["progress"]["state"])

        response, body = self.solve("tc-nand")
        self.assertEqual(response.status_code, 200, body)
        self.assertEqual(self.ledger_of(body)["level-tc-nand-cleared"]["count"], 1)

    def test_rewards_never_show_up_in_the_teacher_projection(self):
        """奖励是存档里的事，不该变成成绩行（成绩行只在结算时产生）。"""
        self.solve_all()
        self.act("settle")
        self.act("submit")
        row = ChapterProgress.objects.get(user=self.student, chapter_id=CHAPTER)
        self.assertEqual(row.score, 100)
        self.assertIn("rewards", row.state)
        self.assertNotIn("rewards", row.state["circuit"])
