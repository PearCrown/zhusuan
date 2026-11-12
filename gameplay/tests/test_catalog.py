"""关卡结构：主线 / 支线 / 前置 / 区域。

平台的玩法形态还没定（可能是剧情关卡，也可能是大地图 RPG）。所以这里先把
「关卡之间什么关系」变成数据，并把校验做严：前置引用不存在的关卡、出现循环
依赖、route 拼错，在 JSON 里极难用肉眼发现，等页面表现异常再查要花几倍时间。
"""

from django.test import TestCase

from core.api import ApiError
from gameplay import catalog, question_bank


def meta(**overrides):
    base = {
        "levels": {
            "tc-nand": {"route": "main", "order": 1, "region": "工坊", "requires": []},
            "tc-and": {"route": "main", "order": 2, "region": "工坊", "requires": ["tc-nand"]},
            "tc-or": {"route": "side", "order": 1, "region": "营帐", "requires": []},
            "tc-xor": {"route": "side", "order": 2, "region": "营帐", "requires": ["tc-or"]},
            "tc-half-adder": {"route": "main", "order": 3, "region": "洛水", "requires": ["tc-and"]},
        }
    }
    base.update(overrides)
    return base


ALL = tuple(question_bank.CIRCUIT_PUZZLES)


class CatalogValidationTests(TestCase):
    def test_shipped_catalog_covers_every_level(self):
        loaded = catalog.load_catalog()
        for level_id in ALL:
            self.assertIn(level_id, loaded["levels"])

    def test_shipped_catalog_has_no_cycles(self):
        # 只要 load_catalog 没抛错就说明无环，这里再确认一遍数据可读
        self.assertTrue(catalog.load_catalog()["levels"])

    def test_unknown_level_is_rejected(self):
        data = meta()
        data["levels"]["tc-nope"] = {"route": "main", "order": 9, "region": "x", "requires": []}
        with self.assertRaises(ApiError) as caught:
            catalog.validate(data, ALL)
        self.assertIn("tc-nope", caught.exception.message)

    def test_missing_level_is_reported(self):
        data = meta()
        del data["levels"]["tc-xor"]
        with self.assertRaises(ApiError) as caught:
            catalog.validate(data, ALL)
        self.assertIn("tc-xor", caught.exception.message)

    def test_bad_route_is_rejected(self):
        data = meta()
        data["levels"]["tc-nand"]["route"] = "mainline"
        with self.assertRaises(ApiError):
            catalog.validate(data, ALL)

    def test_dependency_on_unknown_level_is_rejected(self):
        data = meta()
        data["levels"]["tc-nand"]["requires"] = ["tc-ghost"]
        with self.assertRaises(ApiError) as caught:
            catalog.validate(data, ALL)
        self.assertIn("tc-ghost", caught.exception.message)

    def test_self_dependency_is_rejected(self):
        data = meta()
        data["levels"]["tc-nand"]["requires"] = ["tc-nand"]
        with self.assertRaises(ApiError):
            catalog.validate(data, ALL)

    def test_cycle_is_rejected_with_the_path(self):
        data = meta()
        data["levels"]["tc-nand"]["requires"] = ["tc-and"]
        with self.assertRaises(ApiError) as caught:
            catalog.validate(data, ALL)
        self.assertIn("成环", caught.exception.message)

    def test_order_must_be_an_integer(self):
        data = meta()
        data["levels"]["tc-nand"]["order"] = "第一"
        with self.assertRaises(ApiError):
            catalog.validate(data, ALL)

    def test_route_lookup_defaults_for_unknown_level(self):
        self.assertEqual(catalog.route_of("tc-nand")["route"], "main")
        self.assertEqual(catalog.route_of("tc-hand-adder")["route"], "main")
        self.assertEqual(catalog.route_of("tc-hand-adder")["requires"], [])
