"""剧情数据的契约。

剧情是数据文件，最容易被改坏的地方不是代码而是手写的 JSON。所以这里同时
测两件事：接口能不能把剧情送出去，以及写错时会不会立刻响亮地失败——
静默失败会让页面变成一片空白，那是最难查的一种故障。
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from accounts.roles import STUDENT
from core.api import ApiError
from gameplay import question_bank
from gameplay import story as story_module

User = get_user_model()
PASSWORD = "Bamboo!River-7429-Cloud"
URL = "/game/api/circuit/story"


def minimal_story(**overrides):
    data = {
        "npcs": {"wu-ding": {"name": "武丁", "seal": "丁"}},
        "opening": {"speaker": "wu-ding", "lines": ["开场"]},
        "closing": {"speaker": "wu-ding", "lines": ["收尾"]},
        "levels": {
            "tc-nand": {"speaker": "wu-ding", "quest": "铸与非", "objective": "目标",
                        "intro": ["甲"], "cleared": ["乙"]},
        },
    }
    data.update(overrides)
    return data


class StoryValidationTests(TestCase):
    def test_shipped_story_covers_every_registered_puzzle(self):
        loaded = story_module.load_story()
        for puzzle_id in question_bank.CIRCUIT_PUZZLES:
            self.assertIn(puzzle_id, loaded["levels"], f"{puzzle_id} 缺少剧情")
            self.assertIn(loaded["levels"][puzzle_id]["speaker"], loaded["npcs"])

    def test_level_for_an_unregistered_puzzle_is_rejected(self):
        data = minimal_story()
        data["levels"]["tc-nope"] = dict(data["levels"]["tc-nand"])
        with self.assertRaises(ApiError) as caught:
            story_module.validate(data, tuple(question_bank.CIRCUIT_PUZZLES))
        self.assertIn("tc-nope", caught.exception.message)

    def test_missing_level_is_reported_explicitly(self):
        with self.assertRaises(ApiError) as caught:
            story_module.validate(minimal_story(), ("tc-nand", "tc-and"))
        self.assertIn("tc-and", caught.exception.message)
        self.assertIn("还没有剧情", caught.exception.message)

    def test_unknown_speaker_is_rejected(self):
        data = minimal_story()
        data["levels"]["tc-nand"]["speaker"] = "ghost"
        with self.assertRaises(ApiError) as caught:
            story_module.validate(data, ("tc-nand",))
        self.assertIn("ghost", caught.exception.message)

    def test_npc_without_seal_is_rejected(self):
        data = minimal_story()
        del data["npcs"]["wu-ding"]["seal"]
        with self.assertRaises(ApiError) as caught:
            story_module.validate(data, ("tc-nand",))
        self.assertIn("seal", caught.exception.message)

    def test_non_list_lines_are_rejected(self):
        data = minimal_story()
        data["levels"]["tc-nand"]["intro"] = "这不是数组"
        with self.assertRaises(ApiError):
            story_module.validate(data, ("tc-nand",))


class StoryEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.alice = User.objects.create_user("alice01", display_name="小明", password=PASSWORD)
        cls.alice.groups.add(Group.objects.get(name=STUDENT))

    def test_requires_login(self):
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_serves_the_story_with_speakers_resolvable(self):
        self.client.force_login(self.alice)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        story = response.json()["data"]["story"]
        self.assertTrue(story["chapterTitle"])
        self.assertIn("npcs", story)
        for puzzle_id, level in story["levels"].items():
            self.assertIn(puzzle_id, question_bank.CIRCUIT_PUZZLES)
            self.assertIn(level["speaker"], story["npcs"])

    def test_query_parameters_are_refused(self):
        self.client.force_login(self.alice)
        response = self.client.get(URL + "?debug=1")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_query")
