"""皮肤层：主题、布局、界面文案。

这一层的存在理由：平台的风格会反复推翻重做（剧情游戏 ↔ 大地图 RPG ↔ 工具风）。
所以「长什么样」必须是配置，而不是散在代码里的散装样式与文案。这里测的四件事
都是将来换风格时最容易踩的坑：主题文件不存在、布局名拼错、文案缺字段、
页面没把皮肤真的用上。
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts.roles import STUDENT
from gameplay import skin
from gameplay.skin import SkinError

User = get_user_model()
PASSWORD = "Bamboo!River-7429-Cloud"
PAGE = "/game/circuit"


class SkinResolutionTests(TestCase):
    def test_both_shipped_themes_are_discoverable(self):
        themes = skin.available_themes()
        self.assertIn("bronze-forge", themes)
        self.assertIn("ink-tool", themes)

    def test_default_skin_resolves_without_warnings(self):
        resolved = skin.resolve_skin()
        self.assertEqual(resolved["theme"], "bronze-forge")
        self.assertEqual(resolved["layout"], "forge")
        self.assertEqual(resolved["warnings"], [])
        self.assertEqual(resolved["theme_href"], "css/themes/bronze-forge.css")

    def test_unknown_theme_falls_back_and_reports(self):
        resolved = skin.resolve_skin(theme="no-such-theme")
        self.assertEqual(resolved["theme"], "bronze-forge")
        self.assertTrue(any("no-such-theme" in warning for warning in resolved["warnings"]))

    def test_unknown_layout_falls_back_and_reports(self):
        resolved = skin.resolve_skin(layout="map-not-built-yet")
        self.assertEqual(resolved["layout"], "forge")
        self.assertTrue(any("map-not-built-yet" in warning for warning in resolved["warnings"]))

    def test_alternate_theme_and_layout_can_be_selected(self):
        resolved = skin.resolve_skin(theme="ink-tool", layout="stage")
        self.assertEqual(resolved["theme"], "ink-tool")
        self.assertEqual(resolved["layout"], "stage")
        self.assertEqual(resolved["theme_href"], "css/themes/ink-tool.css")

    @override_settings(GAME_THEME="ink-tool", GAME_LAYOUT="stage")
    def test_settings_decide_the_skin(self):
        resolved = skin.resolve_skin()
        self.assertEqual((resolved["theme"], resolved["layout"]), ("ink-tool", "stage"))


class UiStringsTests(TestCase):
    def test_every_required_string_is_present(self):
        strings = skin.load_ui_strings()
        for key in skin.REQUIRED_KEYS:
            self.assertIsInstance(strings[key], str, key)
            self.assertTrue(strings[key].strip(), key)

    def test_missing_key_is_a_loud_error(self):
        """缺文案要报错：页面上出现空白按钮是最难查的一类问题。"""
        broken = {key: "值" for key in skin.REQUIRED_KEYS}
        del broken["actionSubmit"]
        with self.assertRaises(SkinError) as caught:
            skin._load_uncached(self._write_temp(broken))
        self.assertIn("actionSubmit", str(caught.exception))

    def test_empty_string_counts_as_missing(self):
        blank = {key: "值" for key in skin.REQUIRED_KEYS}
        blank["continue"] = "   "
        with self.assertRaises(SkinError) as caught:
            skin._load_uncached(self._write_temp(blank))
        self.assertIn("continue", str(caught.exception))

    def _write_temp(self, payload):
        import json
        import tempfile
        from pathlib import Path

        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with handle as stream:
            json.dump(payload, stream, ensure_ascii=False)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)


class PageUsesTheSkinTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.alice = User.objects.create_user("alice01", display_name="小明", password=PASSWORD)
        cls.alice.groups.add(Group.objects.get(name=STUDENT))

    def test_page_carries_theme_and_layout_attributes(self):
        self.client.force_login(self.alice)
        response = self.client.get(PAGE)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-theme="bronze-forge"')
        self.assertContains(response, 'data-layout="forge"')
        self.assertContains(response, "css/themes/bronze-forge.css")
        # 文案层真的被渲染进页面（模板用的是 ui_strings.json 的值）
        self.assertContains(response, "返回主页")
        self.assertContains(response, "呈上验符")

    @override_settings(GAME_THEME="ink-tool", GAME_LAYOUT="stage")
    def test_switching_configuration_changes_the_page(self):
        self.client.force_login(self.alice)
        response = self.client.get(PAGE)
        self.assertContains(response, 'data-theme="ink-tool"')
        self.assertContains(response, 'data-layout="stage"')
        self.assertContains(response, "css/themes/ink-tool.css")
