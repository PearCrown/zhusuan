"""第二个章节（夏社）：多 NPC、条件选句、互不串状态。

这一组用例同时是「插件式」的证明：整个章节只新增了
`gameplay/court_chapter.py` + 两个数据文件 + `chapters.py` 末尾的一行 import，
框架文件（services / models / core.api / classrooms.access）一行未改。
"""

import json
import re
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from accounts.roles import STUDENT
from gameplay.chapters import get_chapter
from gameplay.models import ChapterProgress
from gameplay.tests.test_circuit_chapter import ChapterClientMixin

User = get_user_model()
PASSWORD = "Bamboo!River-7429-Cloud"

CHAPTER = "xia-court"


class CourtClientMixin(ChapterClientMixin):
    chapter_id = CHAPTER


class CourtChapterTests(CourtClientMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.student = User.objects.create_user("court_student", display_name="夏社同学", password=PASSWORD)
        cls.student.groups.add(Group.objects.get(name=STUDENT))

    def setUp(self):
        super().setUp()
        self.login(self.student)
        data = self.load_progress()
        self.revision = data["progress"]["revision"]
        self.save_context = data["saveContext"]

    def talk(self, npc):
        response, body = self.act("talk", npcId=npc)
        self.assertEqual(response.status_code, 200, body)
        return body["data"]["progress"]["state"]["npcs"][npc]["dialogue"]

    def lines(self, dialogue):
        return [line for page in dialogue["pages"] for line in page["lines"]]

    def choice_ids(self, dialogue):
        return [choice["id"] for page in dialogue["pages"] for choice in page.get("choices", [])]

    # ---------- 章节本身 ----------
    def test_chapter_is_registered_without_touching_the_framework(self):
        chapter = get_chapter(CHAPTER)
        self.assertEqual(chapter.kind, "story")
        self.assertIsNone(chapter.grade, "纯剧情章节没有分数")
        self.assertNotIn("submit", chapter.actions, "本章不结算，所以也没有 submit")
        body = self.client.get("/game/api/chapters").json()
        ids = {item["chapterId"]: item for item in body["data"]["chapters"]}
        self.assertIn(CHAPTER, ids)
        self.assertEqual(ids[CHAPTER]["kind"], "story")

    # ---------- 两个 NPC ----------
    def test_two_npcs_talk_independently(self):
        wu_ding = self.talk("wu-ding")
        self.assertEqual(wu_ding["npcId"], "wu-ding")
        self.assertEqual(wu_ding["speaker"]["name"], "武丁")

        fu_hao = self.talk("fu-hao")
        self.assertEqual(fu_hao["npcId"], "fu-hao")
        self.assertEqual(fu_hao["speaker"]["name"], "妇好")

        state = self.load_progress()["progress"]["state"]
        # 两个人各自留着自己那份对话快照，后说的不会覆盖先说的。
        self.assertEqual(state["npcs"]["wu-ding"]["dialogue"]["npcId"], "wu-ding")
        self.assertEqual(state["npcs"]["fu-hao"]["dialogue"]["npcId"], "fu-hao")

    def test_accepting_for_one_npc_does_not_touch_the_other(self):
        self.talk("wu-ding")
        response, _ = self.act("accept", npcId="wu-ding")
        self.assertEqual(response.status_code, 200)

        state = self.load_progress()["progress"]["state"]["npcs"]
        self.assertEqual(state["wu-ding"]["quest"], "accepted")
        self.assertEqual(state["fu-hao"]["quest"], "not_started", "另一个人的任务状态不该被带动")
        self.assertIsNone(state["fu-hao"]["dialogue"], "另一个人的对话也不该被改写")

    def test_story_page_serves_each_npc_and_404s_the_rest(self):
        expected = {
            "wu-ding": ("武丁", "夏社问卜 · 记下城门口令"),
            "fu-hao": ("妇好", "营前点粮 · 清点三座粮仓"),
        }
        for npc, (name, quest_title) in expected.items():
            response = self.client.get(f"/game/story/{CHAPTER}/{npc}")
            self.assertEqual(response.status_code, 200, npc)
            html = response.content.decode()
            self.assertIn(f'data-npc="{npc}"', html)

            # json_script 会把中文转义成 \uXXXX，所以解析后比对而不是搜字符串。
            meta = self.stage_json(html, "quest-meta")
            self.assertEqual(meta["title"], quest_title, f"{npc} 的任务文案串了")
            stage = self.stage_json(html, "story-data")
            self.assertEqual(stage["npc"]["name"], name, f"{npc} 的布景串了")
            # 立绘：每个 NPC 都指向自己的那份素材
            self.assertEqual(stage["npc"]["portrait"], f"/static/img/portraits/{npc}-silk.png")
            self.assertIn('data-back="/game/#camp"', html)

        self.assertEqual(self.client.get(f"/game/story/{CHAPTER}/nobody").status_code, 404)

    def stage_json(self, html, element_id):
        match = re.search(rf'<script id="{element_id}" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(match, f"页面没有下发 {element_id}")
        return json.loads(match.group(1))

    def test_unknown_npc_is_a_404(self):
        response, body = self.act("talk", npcId="nobody")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(body["error"]["code"], "npc_not_found")

    # ---------- 条件选句（走真实链路） ----------
    def test_three_quest_states_say_three_different_things(self):
        fresh = self.lines(self.talk("wu-ding"))
        self.assertIn("两问一答。答得上来，我便许你在夏社行走。", fresh)

        self.act("accept", npcId="wu-ding")
        accepted = self.lines(self.load_progress()["progress"]["state"]["npcs"]["wu-ding"]["dialogue"])
        self.assertIn("差事既已在你名下，就别在殿上站着。", accepted)
        self.assertNotIn("两问一答。答得上来，我便许你在夏社行走。", accepted)

        self.act("report", npcId="wu-ding")
        submitted = self.lines(self.load_progress()["progress"]["state"]["npcs"]["wu-ding"]["dialogue"])
        self.assertIn("口令记下了，话也答了。夏社的账上，往后有你一笔。", submitted)
        self.assertNotIn("差事既已在你名下，就别在殿上站着。", submitted)

    def test_invisible_lines_never_reach_the_client(self):
        payload = str(self.talk("wu-ding"))
        self.assertNotIn("口令记下了", payload, "已复命的台词不该在未接任务时出现")
        self.assertNotIn("差事既已在你名下", payload)

    def test_a_story_flag_from_one_npc_changes_another(self):
        before = self.lines(self.talk("fu-hao"))
        self.assertNotIn("口令你也知道，那便不是外人。", before)

        # 武丁那页点「记下城门口令」→ 写下 gateWord 旗标
        self.talk("wu-ding")
        response, body = self.act("remember", npcId="wu-ding", flag="gateWord")
        self.assertEqual(response.status_code, 200, body)
        self.assertTrue(body["data"]["progress"]["state"]["flags"]["gateWord"])

        after = self.lines(self.talk("fu-hao"))
        self.assertIn("口令你也知道，那便不是外人。", after)

    def test_completing_one_quest_changes_another_npcs_lines(self):
        before = self.lines(self.talk("fu-hao"))
        self.assertNotIn("王上那边的事既已了结，你就更该闲下来了。", before)

        self.talk("wu-ding")
        self.act("accept", npcId="wu-ding")
        self.act("report", npcId="wu-ding")

        after = self.lines(self.talk("fu-hao"))
        self.assertIn("王上那边的事既已了结，你就更该闲下来了。", after)
        # 但妇好自己的任务状态没变——条件可见，进度独立。
        self.assertEqual(self.load_progress()["progress"]["state"]["npcs"]["fu-hao"]["quest"], "not_started")

    def test_unknown_flag_is_rejected(self):
        self.talk("wu-ding")
        response, body = self.act("remember", npcId="wu-ding", flag="openTheGate")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "validation_error")

    # ---------- 奖励与成绩 ----------
    def test_reward_is_granted_once_and_rewatching_does_not_pay_again(self):
        self.talk("wu-ding")
        self.act("accept", npcId="wu-ding")
        self.act("report", npcId="wu-ding")

        ledger = self.load_progress()["progress"]["state"]["rewards"]
        self.assertEqual(ledger["quest-wuding-word"]["count"], 1)

        # 重看剧情（talk 再走一遍）不会多拿一份。
        self.talk("wu-ding")
        again = self.load_progress()["progress"]["state"]["rewards"]
        self.assertEqual(again["quest-wuding-word"]["count"], 1)

        # 再复命一次直接被拒，奖励更没有第二次机会。
        response, _ = self.act("report", npcId="wu-ding")
        self.assertEqual(response.status_code, 409)

    def test_pure_story_chapter_never_writes_a_score(self):
        self.talk("wu-ding")
        self.act("accept", npcId="wu-ding")
        self.act("report", npcId="wu-ding")
        row = ChapterProgress.objects.get(user=self.student, chapter_id=CHAPTER)
        self.assertIsNone(row.score)
        self.assertIsNone(row.submitted_at)
        # 教师端的投影只收 score 非空的记录，所以这个章节天然不可见。
        self.assertFalse(
            ChapterProgress.objects.filter(chapter_id=CHAPTER, score__isnull=False).exists())

    # ---------- 老存档 ----------
    def test_old_save_without_new_keys_keeps_working(self):
        self.talk("wu-ding")
        row = ChapterProgress.objects.get(user=self.student, chapter_id=CHAPTER)
        state = row.state
        for key in ("flags", "cleared", "rewards"):
            state.pop(key, None)
        row.state = state
        row.save(update_fields=["state"])

        body = self.client.get(self.progress_url).json()
        self.assertTrue(body["ok"], body)
        response, body = self.act("talk", npcId="fu-hao")
        self.assertEqual(response.status_code, 200, body)
        self.assertEqual(body["data"]["progress"]["state"]["flags"], {}, "缺失的键就地补默认值")
