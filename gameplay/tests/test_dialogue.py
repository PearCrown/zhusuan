"""对话树的契约。

对话是数据文件，最容易被改坏的是手写的 JSON，而不是代码。所以这里测两件事：

1. 数据写错时会不会立刻响亮地失败（缺 npc、next 指向不存在的节点、入口拼错、
   next 成环）。静默失败会让底部对话条变成一片空白，那是最难查的故障。
2. 服务端展开出的 pages 形状对不对，以及「接任务必须是对话末尾那个选项」
   这条前置判据守不守得住。
"""

import json
import re
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from accounts.models import User
from core.api import ApiError
from gameplay import dialogue as dialogue_module
from gameplay.chapters import get_chapter

PATH = "/game/api/chapters/sample-counting"


def minimal_dialogue(**overrides):
    data = {
        "npc": {"id": "gate.keeper", "name": "守门人", "seal": "卫"},
        "episode": {"title": "样例章", "operation": "样例关卡", "phase": "行动前", "summary": "摘要。"},
        "background": "img/story/bg-shan-shui.jpg",
        "then": {"label": "前往关卡", "url": "/game/level/tc-nand"},
        "quest": {
            "title": "样例委托",
            "route": "main",
            "objective": "把差事办完。",
            "steps": [{"kind": "talk", "text": "对话"}, {"kind": "submit", "text": "呈上"}],
        },
        "entry": {"default": "intro"},
        "nodes": {
            "intro": {"lines": ["第一句"], "next": "offer"},
            "offer": {"lines": ["第二句"], "choices": [
                {"id": "take", "text": "接下", "command": {"action": "accept"}},
                {"id": "decline", "text": "再看看"},
            ]},
        },
    }
    data.update(overrides)
    return data


class DialogueValidationTests(TestCase):
    """写得对要能通过，写得错要能报出来。"""

    def test_shipped_dialogue_is_valid(self):
        loaded = dialogue_module.load_dialogue()
        self.assertEqual(loaded["npc"]["name"], "守门人")
        self.assertIn(loaded["entry"]["default"], loaded["nodes"])

    def test_minimal_dialogue_passes(self):
        self.assertEqual(dialogue_module.validate(minimal_dialogue())["npc"]["seal"], "卫")

    def assert_rejected(self, data, fragment):
        with self.assertRaises(ApiError) as ctx:
            dialogue_module.validate(data)
        self.assertEqual(ctx.exception.code, "dialogue_invalid")
        self.assertEqual(ctx.exception.status, 500)
        self.assertIn(fragment, ctx.exception.message)

    def test_missing_npc_is_rejected(self):
        self.assert_rejected(minimal_dialogue(npc={"id": "x"}), "npc 缺少 name")

    def test_missing_node_body_is_rejected(self):
        data = minimal_dialogue()
        data["nodes"]["intro"] = {"next": "offer"}
        self.assert_rejected(data, "intro 的 lines")

    def test_empty_line_is_rejected(self):
        data = minimal_dialogue()
        data["nodes"]["intro"] = {"lines": [""], "next": "offer"}
        self.assert_rejected(data, "intro 的 lines")

    def test_next_pointing_nowhere_is_rejected(self):
        data = minimal_dialogue()
        data["nodes"]["intro"]["next"] = "missing"
        self.assert_rejected(data, "指向不存在的节点 missing")

    def test_entry_pointing_nowhere_is_rejected(self):
        self.assert_rejected(minimal_dialogue(entry={"default": "missing"}), "entry.default")

    def test_unknown_entry_state_is_rejected(self):
        self.assert_rejected(minimal_dialogue(entry={"default": "intro", "finish": "offer"}), "未知状态键 finish")

    def test_choice_without_text_is_rejected(self):
        data = minimal_dialogue()
        data["nodes"]["offer"]["choices"] = [{"id": "take"}]
        self.assert_rejected(data, "缺少 text")

    def test_duplicate_choice_id_is_rejected(self):
        data = minimal_dialogue()
        data["nodes"]["offer"]["choices"] = [{"id": "a", "text": "一"}, {"id": "a", "text": "二"}]
        self.assert_rejected(data, "选项 id 重复")

    def test_command_without_action_is_rejected(self):
        data = minimal_dialogue()
        data["nodes"]["offer"]["choices"] = [{"id": "a", "text": "一", "command": {}}]
        self.assert_rejected(data, "command 缺少 action")

    def test_next_cycle_is_rejected(self):
        data = minimal_dialogue()
        data["nodes"]["intro"]["next"] = "offer"
        data["nodes"]["offer"] = {"lines": ["绕回来"], "next": "intro"}
        self.assert_rejected(data, "成环")


class DialogueExpansionTests(TestCase):
    """pages 展开与入口选择。"""

    def test_entry_follows_quest_state(self):
        data = dialogue_module.load_dialogue()
        self.assertEqual(dialogue_module.entry_node(data, "not_started"), "intro")
        self.assertEqual(dialogue_module.entry_node(data, "accepted"), "on-task")
        self.assertEqual(dialogue_module.entry_node(data, "submitted"), "thanks")

    def test_unknown_quest_state_falls_back_to_default(self):
        data = dialogue_module.load_dialogue()
        self.assertEqual(dialogue_module.entry_node(data, "something-else"), "intro")

    def test_next_chain_is_flattened_into_pages(self):
        data = dialogue_module.load_dialogue()
        pages = dialogue_module.build_pages(data, "intro")
        self.assertEqual([page["nodeId"] for page in pages], ["intro", "offer"])
        # 选项只出现在链的最后一页，前面的页只有台词。
        self.assertNotIn("choices", pages[0])
        self.assertEqual([choice["id"] for choice in pages[1]["choices"]], ["take", "decline"])

    def test_speaker_payload_has_no_secret(self):
        speaker = dialogue_module.dialogue_for("not_started")["speaker"]
        self.assertEqual(set(speaker), {"name", "title", "seal", "color", "portrait"})

    def test_accepts_task_only_before_accepting(self):
        self.assertTrue(dialogue_module.accepts_task(dialogue_module.dialogue_for("not_started")))
        self.assertFalse(dialogue_module.accepts_task(dialogue_module.dialogue_for("accepted")))
        self.assertFalse(dialogue_module.accepts_task(dialogue_module.dialogue_for("submitted")))

    def test_accepts_task_tolerates_missing_or_malformed_dialogue(self):
        for value in (None, {}, {"pages": []}, {"pages": [{}]}, "bad"):
            self.assertFalse(dialogue_module.accepts_task(value), value)


class SampleChapterDialogueFlowTests(TestCase):
    """样例章节的状态机：talk 出对话，accept 必须走到对话末尾。"""

    def setUp(self):
        self.chapter = get_chapter("sample-counting")
        self.state = self.chapter.initial_state(self.chapter.question_bank_id, self.chapter.question_bank_version)

    def act(self, action, payload=None):
        self.state = self.chapter.transition(self.state, action, dict(payload or {}))
        return self.state["story"]

    def test_initial_state_has_empty_dialogue(self):
        self.assertIsNone(self.state["story"]["dialogue"])

    def test_talk_returns_multi_page_dialogue(self):
        story = self.act("talk")
        self.assertTrue(story["talkedToNpc"])
        self.assertEqual([page["nodeId"] for page in story["dialogue"]["pages"]], ["intro", "offer"])

    def test_accept_before_talk_is_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            self.act("accept")
        self.assertEqual(ctx.exception.code, "dialogue_incomplete")
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(self.state["story"]["quest"], "not_started")

    def test_accept_after_talk_moves_to_on_task_dialogue(self):
        self.act("talk")
        story = self.act("accept")
        self.assertEqual(story["quest"], "accepted")
        self.assertEqual([page["nodeId"] for page in story["dialogue"]["pages"]], ["on-task"])

    def test_leaving_scene_closes_dialogue(self):
        self.act("talk")
        story = self.act("move", {"scene": "workshop"})
        self.assertIsNone(story["dialogue"])

    def test_old_save_without_dialogue_key_still_loads_and_can_talk(self):
        # 老存档没有 dialogue 键，不能因此 500，也不能让 accept 蒙混过关。
        del self.state["story"]["dialogue"]
        with self.assertRaises(ApiError) as ctx:
            self.act("accept")
        self.assertEqual(ctx.exception.code, "dialogue_incomplete")
        self.assertIn("dialogue", self.act("talk"))

    def test_forged_dialogue_state_is_not_trusted_by_server(self):
        # 客户端不能上传 state，只有动作能被接受；这里直接验证状态机本身
        # 不认"手工塞进去的 dialogue"，仍要求 quest 顺序正确。
        self.state["story"]["dialogue"] = dialogue_module.dialogue_for("not_started")
        self.state["story"]["quest"] = "accepted"
        with self.assertRaises(ApiError) as ctx:
            self.act("accept")
        self.assertEqual(ctx.exception.code, "invalid_transition")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DialogueHttpTests(TestCase):
    """走真实接口：talk 必须把对话随存档一起送出去。

    状态机的单元测试证明不了序列化这一段，这里补上——上一场的教训就是
    「夹具和真实响应不一致，测试骗过自己」。
    """

    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.student = User.objects.create_user("dialogue_student", display_name="对话同学", password="River!Cloud-7268")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.student)
        self.data = self.client.get(PATH + "/progress").json()["data"]

    def post(self, payload):
        csrf = self.client.get("/auth/csrf").json()["data"]["csrfToken"]
        return self.client.post(PATH + "/action", payload, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)

    def act(self, action, **extra):
        response = self.post({"action": action, "revision": self.data["progress"]["revision"],
                              "saveContext": self.data["saveContext"], **extra})
        if response.status_code == 200:
            self.data = response.json()["data"]
        return response

    def test_talk_delivers_dialogue_over_http(self):
        self.assertIsNone(self.data["progress"]["state"]["story"]["dialogue"])
        response = self.act("talk")
        self.assertEqual(response.status_code, 200)
        dialogue = response.json()["data"]["progress"]["state"]["story"]["dialogue"]
        self.assertEqual(dialogue["npcId"], "gate.keeper")
        self.assertEqual([page["nodeId"] for page in dialogue["pages"]], ["intro", "offer"])
        self.assertEqual(dialogue["pages"][-1]["choices"][0]["command"], {"action": "accept"})
        # speaker 只带展示字段，不该夹带任何身份或答案。
        self.assertEqual(set(dialogue["speaker"]), {"name", "title", "seal", "color", "portrait"})

    def test_accept_over_http_requires_the_offer_choice(self):
        self.assertEqual(self.act("accept").status_code, 409)
        self.assertEqual(self.act("talk").status_code, 200)
        response = self.act("accept")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["progress"]["state"]["story"]["quest"], "accepted")

    def test_forged_state_field_is_rejected(self):
        self.act("talk")
        response = self.act("accept", state={"story": {"quest": "accepted"}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_fields")

    def test_game_page_renders_the_dialogue_dom(self):
        html = self.client.get("/game/").content.decode()
        for element_id in ("dialogue", "dialogue-text", "advance-dialogue", "close-dialogue", "camp-back"):
            self.assertIn(f'id="{element_id}"', html, f"game.html 缺少 {element_id}")
        for element_id in ("accept", "submit", "runner", "taskbar"):
            self.assertNotIn(f'id="{element_id}"', html)


class QuestMetaTests(TestCase):
    """任务栏的静态文案。步骤勾选由前端按存档推导，这里只验证文案层。"""

    def assert_rejected(self, data, fragment):
        with self.assertRaises(ApiError) as ctx:
            dialogue_module.validate(data)
        self.assertIn(fragment, ctx.exception.message)

    def test_shipped_quest_meta_shape(self):
        meta = dialogue_module.quest_meta()
        self.assertEqual(meta["route"], "main")
        self.assertTrue(meta["title"])
        self.assertTrue(meta["objective"])
        self.assertEqual([step["kind"] for step in meta["steps"]], ["talk", "answers", "submit"])
        # 只下发文案，不下发任何进度字段。
        self.assertEqual(set(meta), {"title", "objective", "route", "steps"})
        self.assertEqual(set(meta["steps"][0]), {"kind", "text"})

    def test_missing_quest_is_rejected(self):
        data = minimal_dialogue()
        del data["quest"]
        self.assert_rejected(data, "quest 必须是对象")

    def test_quest_missing_objective_is_rejected(self):
        data = minimal_dialogue()
        del data["quest"]["objective"]
        self.assert_rejected(data, "quest 缺少 objective")

    def test_quest_bad_route_is_rejected(self):
        data = minimal_dialogue()
        data["quest"]["route"] = "bonus"
        self.assert_rejected(data, "quest.route")

    def test_quest_empty_steps_is_rejected(self):
        data = minimal_dialogue()
        data["quest"]["steps"] = []
        self.assert_rejected(data, "quest.steps")

    def test_quest_unknown_step_kind_is_rejected(self):
        data = minimal_dialogue()
        data["quest"]["steps"] = [{"kind": "dance", "text": "跳一支"}]
        self.assert_rejected(data, "quest.steps 的 kind")

    def test_quest_step_missing_text_is_rejected(self):
        data = minimal_dialogue()
        data["quest"]["steps"] = [{"kind": "talk"}]
        self.assert_rejected(data, "缺少 text")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class QuestBarRenderTests(TestCase):
    """任务栏要真的被 Django 渲染进页面，且不把进度写死在文案里。"""

    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.student = User.objects.create_user("quest_student", password="River!Cloud-7268")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.student)

    def test_camp_page_does_not_mount_the_quest_component(self):
        html = self.client.get("/game/").content.decode()
        self.assertNotIn('id="quest-bar"', html)
        self.assertNotIn('id="quest-meta"', html)
        self.assertNotIn("js/quest.js", html)

    def test_level_page_mounts_the_same_component(self):
        # 玩家真正提交判分的是关卡页，任务栏必须长在那里，且用的是同一份组件。
        html = self.client.get("/game/level/tc-nand").content.decode()
        self.assertIn('id="quest-slot"', html, "关卡页缺少任务栏挂载点")
        self.assertIn("js/quest.js", html, "关卡页没有引入任务栏组件")
        match = re.search(r'<script id="quest-meta" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(match, "关卡页没有下发任务文案")
        # 关卡是从亳 的「点粮关卡」进来的，任务栏跟着夏社，不是算坊样例。
        self.assertEqual([step["kind"] for step in json.loads(match.group(1))["steps"]], ["answers", "submit"])

    def test_story_page_mounts_the_compact_component(self):
        html = self.client.get("/game/story/sample-counting/gate.keeper").content.decode()
        self.assertIn('id="quest-slot"', html, "剧情页缺少任务栏挂载点")
        self.assertIn('data-variant="compact"', html, "剧情页该用精简版")
        self.assertIn("js/quest.js", html)

    def test_quest_meta_is_not_leaked_into_chapter_state(self):
        # 文案走模板，不该混进用户存档，否则每个账号都存一份同样的文字。
        state = self.client.get(PATH + "/progress").json()["data"]["progress"]["state"]
        self.assertNotIn("quest", state)
        self.assertNotIn("questMeta", state)


class EpisodeMetaTests(TestCase):
    """全屏剧情页的布景数据：落款、背景、演完后的去处。"""

    def assert_rejected(self, data, fragment):
        with self.assertRaises(ApiError) as ctx:
            dialogue_module.validate(data)
        self.assertIn(fragment, ctx.exception.message)

    def test_shipped_presentation_shape(self):
        stage = dialogue_module.presentation()
        self.assertEqual(set(stage), {"episode", "background", "then", "npc", "npcId", "talkFields"})
        self.assertIsInstance(stage["talkFields"], dict)
        self.assertEqual(set(stage["episode"]), {"title", "operation", "phase", "summary"})
        self.assertTrue(stage["then"]["url"].startswith("/"))
        self.assertEqual(stage["npcId"], stage["npc"]["name"] and stage["npcId"])

    def test_missing_episode_is_rejected(self):
        data = minimal_dialogue()
        del data["episode"]
        self.assert_rejected(data, "episode 必须是对象")

    def test_episode_missing_summary_is_rejected(self):
        data = minimal_dialogue()
        del data["episode"]["summary"]
        self.assert_rejected(data, "episode 缺少 summary")

    def test_background_must_be_a_string(self):
        data = minimal_dialogue()
        data["background"] = None
        self.assert_rejected(data, "background 必须是字符串")

    def test_then_url_must_be_site_local(self):
        # 站外地址会把玩家送出站点，必须在数据层就拒掉。
        data = minimal_dialogue()
        data["then"]["url"] = "https://evil.example.com"
        self.assert_rejected(data, "then.url")

    def test_missing_then_is_rejected(self):
        data = minimal_dialogue()
        del data["then"]
        self.assert_rejected(data, "then 必须是对象")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class StoryPageTests(TestCase):
    """全屏剧情页：路由、身份、以及给宿主（A 的地图）的两个跳转参数。"""

    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.student = User.objects.create_user("story_student", password="River!Cloud-7268")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.student)

    def test_anonymous_is_redirected_to_login(self):
        response = Client().get("/game/story/sample-counting/gate.keeper")
        self.assertEqual(response.status_code, 302)

    def test_story_page_renders_full_screen_stage(self):
        html = self.client.get("/game/story/sample-counting/gate.keeper").content.decode()
        for element_id in ("story-stage", "story-bg", "story-portrait", "story-text",
                           "story-speaker-name", "story-choices", "story-skip",
                           "story-log", "story-end", "story-data"):
            self.assertIn(f'id="{element_id}"', html, f"story.html 缺少 {element_id}")
        self.assertIn('class="story-stage"', html)

    def test_story_data_json_matches_presentation(self):
        html = self.client.get("/game/story/sample-counting/gate.keeper").content.decode()
        match = re.search(r'<script id="story-data" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(match, "story-data 未渲染")
        self.assertEqual(json.loads(match.group(1)), dialogue_module.presentation())

    def test_unknown_npc_is_404(self):
        response = self.client.get("/game/story/sample-counting/nobody")
        self.assertEqual(response.status_code, 404)

    def test_unknown_chapter_is_404(self):
        response = self.client.get("/game/story/no-such-chapter/gate.keeper")
        self.assertEqual(response.status_code, 404)

    def test_next_and_back_overrides_are_honoured(self):
        html = self.client.get(
            "/game/story/sample-counting/gate.keeper?next=/game/level/x&back=/game/map").content.decode()
        self.assertIn('data-next="/game/level/x"', html)
        self.assertIn('data-back="/game/map"', html)

    def test_external_redirects_are_rejected(self):
        # //evil.com 与 http:// 都不能被当成站内路径。
        for hostile in ("//evil.example.com", "/%5Cevil.example.com", "http://evil.example.com", "javascript:alert(1)"):
            html = self.client.get(
                f"/game/story/sample-counting/gate.keeper?next={hostile}&back={hostile}").content.decode()
            self.assertNotIn("evil.example.com", html)
            self.assertNotIn("javascript:", html)
            self.assertIn('data-next="/game/#camp"', html)
            self.assertIn('data-back="/game/"', html)

    def test_post_is_refused(self):
        # 页面视图只读；带 CSRF 校验时非安全方法在进入视图前就被拒。
        self.assertEqual(self.client.post("/game/story/sample-counting/gate.keeper").status_code, 403)


class MultiNpcDataTests(TestCase):
    """按 (chapter_id, npc_id) 分文件加载：一个章节可以有多个 NPC。"""

    def test_chapter_directory_lists_its_npcs(self):
        self.assertEqual(dialogue_module.npcs_for("sample-counting"), ("gate.keeper",))
        self.assertEqual(dialogue_module.npcs_for("xia-court"), ("fu-hao", "wu-ding"))
        # 没有数据目录的章节就是空，不是异常。
        self.assertEqual(dialogue_module.npcs_for("no-such-chapter"), ())

    def test_each_npc_loads_its_own_file(self):
        wu_ding = dialogue_module.load_dialogue("xia-court", "wu-ding")
        fu_hao = dialogue_module.load_dialogue("xia-court", "fu-hao")
        self.assertEqual(wu_ding["npc"]["id"], "wu-ding")
        self.assertEqual(fu_hao["npc"]["id"], "fu-hao")
        self.assertNotEqual(wu_ding["quest"]["title"], fu_hao["quest"]["title"])

    def test_unknown_npc_is_a_404_not_an_empty_dialogue(self):
        """缺失就是缺失：绝不能降级成"这个人无话可说"。"""
        with self.assertRaises(ApiError) as ctx:
            dialogue_module.load_dialogue("xia-court", "nobody")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.code, "npc_not_found")

    def test_unknown_chapter_is_a_404(self):
        with self.assertRaises(ApiError) as ctx:
            dialogue_module.load_dialogue("no-such-chapter", "wu-ding")
        self.assertEqual(ctx.exception.status, 404)

    def test_ids_are_not_used_as_paths(self):
        """npcId 来自 URL，必须挡住目录穿越。"""
        for bad in ("../gate.keeper", "/etc/passwd", "wu-ding/../fu-hao", "Wu-Ding", ""):
            with self.assertRaises(ApiError) as ctx:
                dialogue_module.load_dialogue("xia-court", bad)
            self.assertEqual(ctx.exception.status, 404, bad)

    def test_talk_fields_are_declared_in_data(self):
        """多 NPC 章节的 talk 要带 npcId，这个字段由数据声明而不是前端猜。"""
        stage = dialogue_module.presentation("xia-court", "wu-ding")
        self.assertEqual(stage["talkFields"], {"npcId": "wu-ding"})
        self.assertEqual(stage["npcId"], "wu-ding")
        # 单 NPC 的老章节没有声明，就是空字段，行为不变。
        self.assertEqual(dialogue_module.presentation()["talkFields"], {})


class ConditionalLinesTests(TestCase):
    """条件选句：服务端只下发当前可见的节点。"""

    def pages(self, quest, npc_id="wu-ding", **context):
        return dialogue_module.dialogue_for(quest, chapter_id="xia-court", npc_id=npc_id, **context)["pages"]

    def lines_of(self, pages):
        return [line for page in pages for line in page["lines"]]

    def test_three_quest_states_show_three_different_lines(self):
        fresh = self.lines_of(self.pages("not_started"))
        accepted = self.lines_of(self.pages("accepted"))
        submitted = self.lines_of(self.pages("submitted"))

        fresh_line = "两问一答。答得上来，我便许你在夏社行走。"
        accepted_line = "差事既已在你名下，就别在殿上站着。"
        submitted_line = "口令记下了，话也答了。夏社的账上，往后有你一笔。"

        self.assertIn(fresh_line, fresh)
        self.assertIn(accepted_line, accepted)
        self.assertIn(submitted_line, submitted)

        # 三种状态各说各的那一句，且看不到另外两句——这就是 when 的验收。
        for line, mine, others in (
            (fresh_line, fresh, (accepted, submitted)),
            (accepted_line, accepted, (fresh, submitted)),
            (submitted_line, submitted, (fresh, accepted)),
        ):
            self.assertIn(line, mine)
            for other in others:
                self.assertNotIn(line, other)

    def test_choices_are_filtered_by_state_too(self):
        """同一个终点节点，按任务状态给出不同的按钮。"""
        def ids(state):
            return [choice["id"] for page in self.pages(state) for choice in page.get("choices", [])]
        self.assertEqual(ids("not_started"), ["take"])
        self.assertEqual(ids("accepted"), ["remember", "report"])
        self.assertEqual(ids("submitted"), [], "已复命的人不该再看到任何选项")

    def test_invisible_lines_are_never_sent(self):
        """条件不满足的台词不能出现在响应里——否则等于剧透。"""
        payload = json.dumps(self.pages("not_started"), ensure_ascii=False)
        self.assertNotIn("口令记下了", payload)
        self.assertNotIn("差事既已在你名下", payload)
        # 而当前该看到的那句必须在。
        self.assertIn("两问一答", payload)

        payload = json.dumps(self.pages("accepted"), ensure_ascii=False)
        self.assertNotIn("两问一答", payload)
        self.assertNotIn("口令记下了", payload)

    def test_flags_change_what_an_npc_says(self):
        without = self.lines_of(self.pages("not_started", npc_id="fu-hao"))
        with_flag = self.lines_of(self.pages("not_started", npc_id="fu-hao", flags={"gateWord": True}))
        self.assertNotIn("口令你也知道，那便不是外人。", without)
        self.assertIn("口令你也知道，那便不是外人。", with_flag)

    def test_cleared_levels_change_what_an_npc_says(self):
        without = self.lines_of(self.pages("not_started", npc_id="fu-hao"))
        with_clear = self.lines_of(
            self.pages("not_started", npc_id="fu-hao", flags={"gateWord": True}, cleared=("wu-ding",)))
        self.assertNotIn("王上那边的事既已了结", "".join(without))
        self.assertIn("王上那边的事既已了结，你就更该闲下来了。", with_clear)

    def test_conditions_are_anded(self):
        """quest / flags / cleared 之间是 AND，不是 OR。"""
        data = minimal_dialogue(nodes={
            "intro": {"lines": ["可见"], "next": "gated"},
            "gated": {"when": {"quest": ["accepted"], "flags": {"ok": True}}, "lines": ["两道门都开"]},
        })
        dialogue_module.validate(data)
        context = {"quest": "accepted", "flags": {"ok": True}, "cleared": ()}
        self.assertEqual([p["nodeId"] for p in dialogue_module.build_pages(data, "intro", context)],
                         ["intro", "gated"])
        context = {"quest": "accepted", "flags": {}, "cleared": ()}
        self.assertEqual([p["nodeId"] for p in dialogue_module.build_pages(data, "intro", context)], ["intro"])


class WhenValidationTests(TestCase):
    """when 写错等于悄悄换了台词分支，必须当场报错。"""

    def reject(self, node, fragment):
        data = minimal_dialogue(nodes={
            "intro": {"lines": ["第一句"], "next": "offer"},
            "offer": {"lines": ["第二句"], **node},
        })
        with self.assertRaises(ApiError) as ctx:
            dialogue_module.validate(data)
        self.assertIn(fragment, ctx.exception.message)

    def test_unknown_condition_key_is_rejected(self):
        self.reject({"when": {"mood": ["happy"]}}, "未知条件 mood")

    def test_unknown_quest_state_is_rejected(self):
        self.reject({"when": {"quest": ["dreaming"]}}, "未知状态")

    def test_empty_when_is_rejected(self):
        self.reject({"when": {}}, "when 必须是非空对象")

    def test_flag_value_must_be_boolean(self):
        self.reject({"when": {"flags": {"ok": "yes"}}}, "必须是布尔值")

    def test_cleared_must_be_an_array(self):
        self.reject({"when": {"cleared": "tc-nand"}}, "when.cleared 必须是非空数组")

    def test_choices_and_next_together_are_rejected(self):
        """带选项的节点是链的终点；同时有 next 会把选项之后的台词送出去。"""
        data = minimal_dialogue(nodes={
            "intro": {"lines": ["第一句"], "choices": [{"id": "a", "text": "好"}], "next": "offer"},
            "offer": {"lines": ["第二句"]},
        })
        with self.assertRaises(ApiError) as ctx:
            dialogue_module.validate(data)
        self.assertIn("既有 choices 又有 next", ctx.exception.message)
