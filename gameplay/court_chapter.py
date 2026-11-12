"""夏社：第二个章节，用来证明「加一整章不改框架一行代码」。

它只做三件事，全部靠数据与本章节自己的代码完成：

1. 两个 NPC（武丁 / 妇好）各有自己的对话文件与自己的任务；
   NPC 清单来自 `data/dialogue/xia-court/` 目录，代码里没有硬编码任何一个 id。
2. 两个 NPC 的任务状态互不串：各自一份 `state.npcs[<npcId>]`，
   对一个 NPC 的 accept / report 不会改动另一个的 quest。
3. 条件选句（`when`）跑在真实链路上：任务状态、章节旗标都参与判断，
   条件不满足的台词服务端根本不下发。

这个章节是纯剧情：`kind="story"`（沿用现有取值，不需要新契约）、`grade=None`、
不注册 `submit`——所以它既不会写成绩，也不会被"一次性结算"锁死，
教师端的成绩投影里天然看不到它。

注册方式只有一处：`gameplay/chapters.py` 末尾的一行 import。
"""

from copy import deepcopy

from core.api import ApiError

from . import dialogue, rewards
from .chapters import Chapter, register
from .dialogue import accepts_task, dialogue_for

CHAPTER_ID = "xia-court"

# NPC 清单由数据目录决定：加一个 NPC = 加一个 json 文件，不用改这里。
NPCS = dialogue.npcs_for(CHAPTER_ID)

# 对话选项里能写下的故事旗标白名单。旗标名写错是内容错误，要当场报。
KNOWN_FLAGS = ("gateWord",)


def invalid():
    return ApiError("invalid_transition", "当前不能执行这一步，请按章节提示操作。", 409)


def initial_state(bank_id, bank_version):
    return {
        "npcs": {npc: {"talkedToNpc": False, "quest": "not_started", "dialogue": None} for npc in NPCS},
        # 旗标是章节级事实（"听说过口令"），任务状态是各 NPC 私有的——两者不混。
        "flags": {},
        # 已完成项：本章没有关卡，这里记"哪个 NPC 的委托已复命"，
        # 对话层的 when.cleared 用同一份数据判断。
        "cleared": [],
        "rewards": {},
    }


def _npc_of(state, payload):
    npc_id = payload.get("npcId")
    if not isinstance(npc_id, str) or npc_id not in state["npcs"]:
        raise ApiError("npc_not_found", "此处没有可以对话的人。", 404)
    return state["npcs"][npc_id], npc_id


def _refresh(state, npc, npc_id):
    """按当前状态重算这名 NPC 的对话快照。

    flags / cleared 一并传下去：条件选句要看它们，而过滤发生在服务端。
    """
    npc["dialogue"] = dialogue_for(npc["quest"], chapter_id=CHAPTER_ID, npc_id=npc_id,
                                   flags=state["flags"], cleared=state["cleared"])


def transition(state, action, payload):
    state = deepcopy(state)
    # 老存档没有这些键时就地补默认值，不升 schema_version。
    state.setdefault("flags", {})
    state.setdefault("cleared", [])
    state.setdefault("rewards", {})

    if action == "talk":
        npc, npc_id = _npc_of(state, payload)
        npc["talkedToNpc"] = True
        _refresh(state, npc, npc_id)

    elif action == "accept":
        npc, npc_id = _npc_of(state, payload)
        if npc["quest"] != "not_started":
            raise invalid()
        # 接任务的前提是"对话已经走到末尾那个选项"，客户端绕不过去。
        if not accepts_task(npc.get("dialogue")):
            raise ApiError("dialogue_incomplete", "请先与他把话说完。", 409)
        npc["quest"] = "accepted"
        _refresh(state, npc, npc_id)

    elif action == "remember":
        # 对话选项写下一条章节旗标：别的 NPC 的台词可以据此变化。
        npc, npc_id = _npc_of(state, payload)
        flag = payload.get("flag")
        if flag not in KNOWN_FLAGS:
            raise ApiError("validation_error", "未知的旗标。")
        state["flags"][flag] = True
        _refresh(state, npc, npc_id)

    elif action == "report":
        npc, npc_id = _npc_of(state, payload)
        if npc["quest"] != "accepted":
            raise invalid()
        npc["quest"] = "submitted"
        # 记进"已完成项"：另一个 NPC 的台词可以用 when.cleared 判断"这人办完了没有"。
        # 对电路章节 cleared 放的是关卡 id，对本章节放的是办完的委托，语义都是
        # "这个章节自己维护的已完成项"。
        if npc_id not in state["cleared"]:
            state["cleared"].append(npc_id)
        # 任务奖励：账本保证同一 rewardId 只发一次（见 gameplay/rewards.py），
        # 玩家把这段对话重看一遍也领不到第二份。
        reward_id = dialogue.load_dialogue(CHAPTER_ID, npc_id).get("reward")
        if reward_id:
            rewards.grant(state, reward_id, at=_now())
        _refresh(state, npc, npc_id)

    else:
        raise ApiError("invalid_action", "不支持此章节操作。")

    return state


def _now():
    """时间戳只用于奖励账本；放在函数里是为了让 transition 本身保持可测。"""
    from django.utils import timezone
    return timezone.now().isoformat(timespec="seconds")


register(Chapter(
    CHAPTER_ID,
    "铸算·夏 · 夏社",
    1,
    initial_state,
    transition,
    None,                                   # 纯剧情：没有分数
    {"talk": {"npcId"}, "accept": {"npcId"}, "remember": {"npcId", "flag"}, "report": {"npcId"}},
    "",                                     # 不挂题库
    "",
    "story",                                # 沿用现有 kind，不需要新契约
))
