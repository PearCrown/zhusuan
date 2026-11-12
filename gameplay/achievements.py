"""成就：全部由服务端从存档推导，不存"已解锁"标记。

为什么不单独存一张成就表：
1. 存档本身就是权威事实（通过了几关、试了几次、是不是满分），
   再存一份标记就会出现"成就说解锁了、存档却没通过"的分叉；
2. 以后改判定条件时，学生回看旧存档能得到重新计算的结果，而不是一堆历史脏数据。

代价是每次读取都要算一遍，但数据量很小（一个学生一章最多几十条记录）。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Achievement:
    id: str
    title: str
    description: str
    # 判定函数：接收"关卡视图"（见 build_level_views 的返回结构）
    check: object


def _levels(circuit):
    return (circuit or {}).get("levels") or {}


def _attempts(circuit):
    return (circuit or {}).get("attempts") or []


def _any_level(circuit, predicate):
    return any(predicate(level) for level in _levels(circuit).values())


ACHIEVEMENTS = [
    Achievement(
        "first-clear",
        "初入算坊",
        "第一次通过一关。",
        lambda c, r: _any_level(c, lambda level: level.get("passed")),
    ),
    Achievement(
        "first-try",
        "一气呵成",
        "一次尝试就通过，没有重来。",
        lambda c, r: _any_level(c, lambda level: level.get("passed") and (level.get("attempts") or 0) == 1),
    ),
    Achievement(
        "full-marks",
        "满算",
        "以满分结算本章。",
        lambda c, r: bool(r) and r.get("score") == r.get("maxScore"),
    ),
    Achievement(
        "no-wrong-row",
        "验符无差",
        "最后一次通过时，真值表逐行全对。",
        lambda c, r: any(
            (level.get("lastResult") or {}).get("passed")
            and all(case.get("pass") for case in (level.get("lastResult") or {}).get("cases", []))
            for level in _levels(c).values()
            if (level.get("lastResult") or {}).get("cases")
        ),
    ),
    Achievement(
        "persistent",
        "三试不折",
        "同一关尝试三次以上才通过。",
        lambda c, r: _any_level(c, lambda level: level.get("passed") and (level.get("attempts") or 0) >= 3),
    ),
    Achievement(
        "settled",
        "入册",
        "完成一次章末结算，成绩入库。",
        lambda c, r: bool(r),
    ),
    Achievement(
        "replay",
        "温故",
        "结算之后又回到关卡重做。",
        lambda c, r: bool(r) and len(_attempts(c)) >= 2,
    ),
    Achievement(
        "all-levels",
        "全关通",
        "通过本章发布的全部关卡。",
        lambda c, r: bool(_levels(c)) and all(level.get("passed") for level in _levels(c).values()),
    ),
]


def evaluate(circuit_state, result):
    """返回 [{id,title,description,unlocked}]，顺序固定，方便前端布局。"""
    circuit = circuit_state or {}
    unlocked = []
    for item in ACHIEVEMENTS:
        try:
            ok = bool(item.check(circuit, result))
        except Exception:      # 判定只影响展示，绝不让它拖垮页面
            ok = False
        unlocked.append({
            "id": item.id,
            "title": item.title,
            "description": item.description,
            "unlocked": ok,
        })
    return unlocked


def evaluate_many(entries):
    """多章合并：同一枚成就，只要有一章满足就算解锁。

    entries: [(circuit_state, result), ...]
    顺序仍按 ACHIEVEMENTS 定义，前端布局稳定。
    """
    unlocked = {}
    for state, result in entries:
        for item in evaluate(state, result):
            unlocked[item["id"]] = unlocked.get(item["id"], False) or item["unlocked"]
    merged = []
    for item in ACHIEVEMENTS:
        merged.append({
            "id": item.id,
            "title": item.title,
            "description": item.description,
            "unlocked": bool(unlocked.get(item.id)),
        })
    return merged
