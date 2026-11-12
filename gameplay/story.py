"""剧情与关卡委托的读取层。

设计原则：文案是数据，不是代码。剧情写在 data/circuit_story.json 里，
改台词、加委托、换立绘都不需要改 Python 或 JS。

读取时会做一致性校验，而且故意在启动时就报错而不是悄悄降级：
剧情文件写错（比如引用了不存在的关卡或人物）是开发者最常犯的错，
让它早点、响亮点失败，比页面上出现一片空白要好。
"""

import json
from pathlib import Path

from core.api import ApiError

from . import question_bank

STORY_PATH = Path(__file__).resolve().parent / "data" / "circuit_story.json"

REQUIRED_NPC_FIELDS = ("name", "seal")
# 交付方式：auto = 在关卡页提交即结算；npc = 必须回 NPC 对话交付。
# 写成数据是为了换玩法不改代码；缺省 auto，老数据不用改。
DELIVER_MODES = ("auto", "npc")
REQUIRED_LEVEL_FIELDS = ("speaker", "quest", "objective", "intro", "cleared")

_cache = None


def _fail(message):
    raise ApiError("story_invalid", f"剧情数据有误：{message}", 500)


def _require(condition, message):
    if not condition:
        _fail(message)


def validate(story, puzzle_ids):
    """校验剧情数据与关卡注册表是否对得上。"""
    _require(isinstance(story, dict), "根节点必须是对象")
    _require(isinstance(story.get("npcs"), dict) and story["npcs"], "npcs 不能为空")

    for npc_id, npc in story["npcs"].items():
        _require(isinstance(npc, dict), f"人物 {npc_id} 必须是对象")
        for field in REQUIRED_NPC_FIELDS:
            _require(isinstance(npc.get(field), str) and npc[field], f"人物 {npc_id} 缺少 {field}")

    levels = story.get("levels")
    _require(isinstance(levels, dict) and levels, "levels 不能为空")

    known = set(story["npcs"])
    for puzzle_id, level in levels.items():
        _require(puzzle_id in puzzle_ids, f"levels 里的 {puzzle_id} 不是已注册的关卡")
        _require(isinstance(level, dict), f"关卡 {puzzle_id} 必须是对象")
        for field in REQUIRED_LEVEL_FIELDS:
            _require(field in level, f"关卡 {puzzle_id} 缺少 {field}")
        _require(level["speaker"] in known, f"关卡 {puzzle_id} 的委托人 {level['speaker']} 不存在")
        for field in ("intro", "cleared", "hint"):
            if field in level:
                _require(isinstance(level[field], list) and all(isinstance(line, str) for line in level[field]),
                         f"关卡 {puzzle_id} 的 {field} 必须是字符串数组")
        # reward 是可选的：奖励是内容，没写就没有奖励，不是机制的一部分。
        reward = level.get("reward")
        _require(reward is None or (isinstance(reward, str) and reward),
                 f"关卡 {puzzle_id} 的 reward 必须是非空字符串")

    for section in ("opening", "closing"):
        if section not in story:
            continue
        block = story[section]
        _require(isinstance(block, dict), f"{section} 必须是对象")
        _require(block.get("speaker") in known, f"{section} 的委托人不存在")
        _require(isinstance(block.get("lines"), list) and block["lines"], f"{section} 的 lines 不能为空")

    missing = [pid for pid in puzzle_ids if pid not in levels]
    _require(not missing, f"以下关卡还没有剧情：{'、'.join(sorted(missing))}")

    deliver = story.get("deliver", "auto")
    _require(deliver in DELIVER_MODES, f"deliver 只能是 {' 或 '.join(DELIVER_MODES)}，收到 {deliver!r}")
    return story


def load_story():
    """读取并校验剧情（进程内缓存；开发者改完重启服务即生效）。"""
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = STORY_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiError("story_unavailable", "剧情文件无法读取，请联系维护人员。", 500) from exc
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ApiError("story_unavailable", "剧情文件不是合法的 JSON，请检查格式。", 500) from exc
    _cache = validate(parsed, tuple(question_bank.CIRCUIT_PUZZLES))
    return _cache


def level_reward(puzzle_id):
    """该关的首次通关奖励 id。数据里没写就返回 None。"""
    level = load_story()["levels"].get(puzzle_id) or {}
    reward = level.get("reward")
    return reward if isinstance(reward, str) and reward else None


def deliver_mode():
    """本章的交付方式。缺省 auto：老数据没写这个键时行为与之前一致。"""
    return load_story().get("deliver", "auto")
