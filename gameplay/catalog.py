"""关卡结构元数据：主线 / 支线 / 前置 / 区域。

现在前端只用它来标「主 / 支」，但结构先定下来，将来做大地图、章节解锁、
支线奖励都不用改代码骨架——这正是「风格待定」时该提前做的事：
把会变的东西放进数据，把不会变的东西放进代码。

校验偏严格：前置指向不存在的关卡、出现循环依赖、route 拼错，都会在读取时
直接报错。这几类错误在数据文件里极难用肉眼发现，等页面表现异常再回头查
要花几倍时间。
"""

import json
from pathlib import Path

from core.api import ApiError

from . import question_bank

META_PATH = Path(__file__).resolve().parent / "data" / "level_meta.json"

ROUTES = ("main", "side")
REQUIRED_FIELDS = ("route", "order", "region")

_cache = None


def _fail(message):
    raise ApiError("catalog_invalid", f"关卡结构数据有误：{message}", 500)


def validate(meta, puzzle_ids):
    _require = lambda condition, message: _fail(message) if not condition else None

    _require(isinstance(meta, dict) and isinstance(meta.get("levels"), dict), "根节点需要 levels 对象")
    levels = meta["levels"]
    _require(bool(levels), "levels 不能为空")

    known = set(puzzle_ids)
    for level_id, item in levels.items():
        _require(level_id in known, f"{level_id} 不是已注册的关卡")
        _require(isinstance(item, dict), f"{level_id} 必须是对象")
        for field in REQUIRED_FIELDS:
            _require(field in item, f"{level_id} 缺少 {field}")
        _require(item["route"] in ROUTES, f"{level_id} 的 route 必须是 main 或 side")
        _require(isinstance(item["order"], int) and not isinstance(item["order"], bool),
                 f"{level_id} 的 order 必须是整数")
        _require(isinstance(item["region"], str) and item["region"], f"{level_id} 的 region 不能为空")
        requires = item.get("requires", [])
        _require(isinstance(requires, list) and all(isinstance(dep, str) for dep in requires),
                 f"{level_id} 的 requires 必须是字符串数组")
        for dependency in requires:
            _require(dependency in levels, f"{level_id} 的前置 {dependency} 没有结构数据")
            _require(dependency != level_id, f"{level_id} 不能把自己当前置")

    # 前置关系不能成环，否则将来做解锁会出现永远打不开的关卡。
    state = {}

    def visit(level_id, trail):
        mark = state.get(level_id)
        if mark == "done":
            return
        if mark == "visiting":
            cycle = " → ".join(trail + [level_id])
            _fail(f"前置关系成环：{cycle}")
        state[level_id] = "visiting"
        for dependency in levels[level_id].get("requires", []):
            visit(dependency, trail + [level_id])
        state[level_id] = "done"

    for level_id in levels:
        visit(level_id, [])

    missing = [level_id for level_id in known if level_id not in levels]
    _require(not missing, f"以下关卡还没有结构数据：{'、'.join(sorted(missing))}")
    return meta


def load_catalog():
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = META_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiError("catalog_unavailable", "关卡结构文件无法读取，请联系维护人员。", 500) from exc
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ApiError("catalog_unavailable", "关卡结构文件不是合法 JSON，请检查格式。", 500) from exc
    _cache = validate(parsed, tuple(question_bank.CIRCUIT_PUZZLES))
    return _cache


def route_of(level_id):
    """返回该关卡的结构信息；没有元数据时给一份中性默认值。"""
    item = load_catalog()["levels"].get(level_id)
    if item is None:
        return {"route": "main", "order": 0, "region": "", "requires": []}
    return {"requires": [], **item}
