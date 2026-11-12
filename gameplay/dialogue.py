"""对话数据层：一个 NPC 一份文件，条件选句由服务端过滤。

为什么按 (chapter_id, npc_id) 分文件：
大地图上会有多个可交互 NPC。整章台词塞在一个文件里，内容作者改一个人的台词
要翻整章；按 NPC 拆分后，文件路径本身就是接口——A 的地图只要记住 npcId，
跳 `/game/story/<chapterId>/<npcId>` 就能落到对应的人身上。

为什么在服务端展开并过滤 `when`：
翻页必须是纯本地动作（100 并发验收正卡在这类请求放大上），所以一次 talk
就把整条链拍平成 pages 一起返回。但**条件不满足的节点绝不能下发**——客户端
看得到的台词等于剧透后面会发生什么。所以过滤发生在 build_pages 里，不是前端的事。

为什么数据写错要响亮报错：
缺 npc、next 指向不存在的节点、入口拼错、`when` 引用了未知状态、next 成环，
这些在手写 JSON 里极难用肉眼发现。降级成"空白对话"会让故障表现为
"点了没反应"，那是最难查的一类。
"""

import json
import re
from pathlib import Path

from core.api import ApiError

DATA_DIR = Path(__file__).resolve().parent / "data" / "dialogue"

# 老调用点（gameplay/chapters.py 的 sample-counting）不带章节/NPC 参数，
# 这里给默认值保持兼容：默认指向样例章节的城门守卒，行为与拆分前一致。
DEFAULT_CHAPTER = "sample-counting"
DEFAULT_NPC = "gate.keeper"

# 章节 / NPC 的 id 会直接拼进文件路径，所以只接受这个白名单字符集。
# 这也是防目录穿越的第二道门（第一道是 views 里"章节必须已注册"）。
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# 任务状态。entry 里除 default 外只接受这几个键。
QUEST_STATES = ("not_started", "accepted", "submitted")

NPC_REQUIRED = ("id", "name", "seal")
SPEAKER_FIELDS = ("name", "title", "seal", "color", "portrait")

# 任务栏步骤的类型。勾选状态由前端按存档推导，数据里只放文案。
QUEST_KINDS = ("talk", "answers", "submit")

# 节点条件支持的三类判断，全部 AND。
WHEN_KEYS = ("quest", "flags", "cleared")

_cache = {}


def _fail(message):
    raise ApiError("dialogue_invalid", f"对话数据有误：{message}", 500)


def _require(condition, message):
    if not condition:
        _fail(message)


# ---------- 校验 ----------
def _validate_choices(node_id, choices):
    _require(isinstance(choices, list) and choices, f"节点 {node_id} 的 choices 必须是非空数组")
    seen = set()
    for choice in choices:
        _require(isinstance(choice, dict), f"节点 {node_id} 的选项必须是对象")
        choice_id, text = choice.get("id"), choice.get("text")
        _require(isinstance(choice_id, str) and choice_id, f"节点 {node_id} 有选项缺少 id")
        _require(choice_id not in seen, f"节点 {node_id} 的选项 id 重复：{choice_id}")
        seen.add(choice_id)
        _require(isinstance(text, str) and text, f"节点 {node_id} 的选项 {choice_id} 缺少 text")
        if "when" in choice:
            _validate_when(f"{node_id}.{choice_id}", choice["when"])
        command = choice.get("command")
        if command is not None:
            _require(isinstance(command, dict), f"节点 {node_id} 的选项 {choice_id} 的 command 必须是对象")
            action = command.get("action")
            _require(isinstance(action, str) and action, f"节点 {node_id} 的选项 {choice_id} 的 command 缺少 action")


def _validate_when(node_id, when):
    """`when` 写错等于悄悄换了台词分支，必须在加载时就拒绝。"""
    _require(isinstance(when, dict) and when, f"节点 {node_id} 的 when 必须是非空对象")

    for key in when:
        _require(key in WHEN_KEYS, f"节点 {node_id} 的 when 含未知条件 {key}（只支持 {' / '.join(WHEN_KEYS)}）")

    quest = when.get("quest")
    if quest is not None:
        states = (quest,) if isinstance(quest, str) else quest
        _require(isinstance(states, (list, tuple)) and states, f"节点 {node_id} 的 when.quest 必须是非空数组或字符串")
        for state in states:
            _require(isinstance(state, str) and state in QUEST_STATES,
                     f"节点 {node_id} 的 when.quest 含未知状态 {state!r}")

    flags = when.get("flags")
    if flags is not None:
        _require(isinstance(flags, dict) and flags, f"节点 {node_id} 的 when.flags 必须是非空对象")
        for flag, value in flags.items():
            _require(isinstance(flag, str) and flag, f"节点 {node_id} 的 when.flags 含空 flag 名")
            _require(isinstance(value, bool), f"节点 {node_id} 的 when.flags.{flag} 必须是布尔值")

    cleared = when.get("cleared")
    if cleared is not None:
        _require(isinstance(cleared, list) and cleared, f"节点 {node_id} 的 when.cleared 必须是非空数组")
        for item in cleared:
            _require(isinstance(item, str) and item, f"节点 {node_id} 的 when.cleared 含空 id")


def _validate_quest(quest):
    _require(isinstance(quest, dict), "quest 必须是对象")
    for field in ("title", "objective"):
        _require(isinstance(quest.get(field), str) and quest[field], f"quest 缺少 {field}")
    _require(quest.get("route") in ("main", "side"), "quest.route 必须是 main 或 side")
    steps = quest.get("steps")
    _require(isinstance(steps, list) and steps, "quest.steps 必须是非空数组")
    for step in steps:
        _require(isinstance(step, dict), "quest.steps 的每一项必须是对象")
        _require(isinstance(step.get("text"), str) and step["text"], "quest.steps 有步骤缺少 text")
        _require(step.get("kind") in QUEST_KINDS, f"quest.steps 的 kind 必须是 {' / '.join(QUEST_KINDS)}")


def _validate_episode(dialogue):
    """跳过确认弹窗要显示的落款信息。缺了它，跳过按钮就只能盲跳。"""
    episode = dialogue.get("episode")
    _require(isinstance(episode, dict), "episode 必须是对象")
    for field in ("title", "operation", "phase", "summary"):
        _require(isinstance(episode.get(field), str) and episode[field], f"episode 缺少 {field}")

    background = dialogue.get("background")
    _require(isinstance(background, str), "background 必须是字符串（可留空）")


def _validate_stage(dialogue):
    """剧情演完后的去处。url 用相对路径，便于换部署和后续接 A 的地图。"""
    then = dialogue.get("then")
    _require(isinstance(then, dict), "then 必须是对象")
    label, url = then.get("label"), then.get("url")
    _require(isinstance(label, str) and label, "then 缺少 label")
    _require(isinstance(url, str) and url.startswith("/"), "then.url 必须是以 / 开头的站内路径")


def validate(dialogue):
    """校验对话数据；任何一处对不上都抛 500，绝不静默降级。"""
    _require(isinstance(dialogue, dict), "根节点必须是对象")

    npc = dialogue.get("npc")
    _require(isinstance(npc, dict), "npc 必须是对象")
    for field in NPC_REQUIRED:
        _require(isinstance(npc.get(field), str) and npc[field], f"npc 缺少 {field}")

    # 可选：talk 动作要带的额外字段。多 NPC 章节靠它告诉前端"启动对话时补上 npcId"，
    # 而不是让前端猜这个章节是单 NPC 还是多 NPC。
    talk_fields = dialogue.get("talkFields", {})
    _require(isinstance(talk_fields, dict), "talkFields 必须是对象")
    for key, value in talk_fields.items():
        _require(isinstance(key, str) and key, "talkFields 的键不能为空")
        _require(isinstance(value, str) and value, f"talkFields.{key} 必须是非空字符串")

    # 可选：这名 NPC 的任务奖励 id。奖励是内容，没写就是没有奖励。
    reward = dialogue.get("reward")
    _require(reward is None or (isinstance(reward, str) and reward), "reward 必须是非空字符串")

    _validate_quest(dialogue.get("quest"))
    _validate_episode(dialogue)
    _validate_stage(dialogue)

    nodes = dialogue.get("nodes")
    _require(isinstance(nodes, dict) and nodes, "nodes 不能为空")

    for node_id, node in nodes.items():
        _require(isinstance(node, dict), f"节点 {node_id} 必须是对象")
        lines = node.get("lines")
        _require(
            isinstance(lines, list) and lines and all(isinstance(line, str) and line for line in lines),
            f"节点 {node_id} 的 lines 必须是非空字符串数组",
        )
        nxt = node.get("next")
        if nxt is not None:
            _require(isinstance(nxt, str) and nxt, f"节点 {node_id} 的 next 必须是非空字符串")
            _require(nxt in nodes, f"节点 {node_id} 的 next 指向不存在的节点 {nxt}")
        if "when" in node:
            _validate_when(node_id, node["when"])
        if "choices" in node:
            _validate_choices(node_id, node["choices"])
            # 带选项的节点是链的终点：选项之后的内容不该被下发，否则等于剧透。
            _require(not nxt, f"节点 {node_id} 既有 choices 又有 next：选项之后不该再有台词")

    entry = dialogue.get("entry")
    _require(isinstance(entry, dict), "entry 必须是对象")
    default = entry.get("default")
    _require(isinstance(default, str) and default in nodes, "entry.default 必须是已存在的节点")
    for key, node_id in entry.items():
        _require(key == "default" or key in QUEST_STATES, f"entry 含未知状态键 {key}")
        _require(node_id in nodes, f"entry.{key} 指向不存在的节点 {node_id}")

    # next 链不能成环：成环会让 build_pages 永远走不完，表现为页面卡死。
    for start in nodes:
        seen, current = set(), start
        while current is not None:
            _require(current not in seen, f"节点 {current} 的 next 链成环")
            seen.add(current)
            current = nodes[current].get("next")
    return dialogue


# ---------- 读取与展开 ----------
def _data_path(chapter_id, npc_id):
    if not SAFE_ID.match(chapter_id) or not SAFE_ID.match(npc_id):
        raise ApiError("npc_not_found", "此处没有可以对话的人。", 404)
    return DATA_DIR / chapter_id / f"{npc_id}.json"


def npcs_for(chapter_id):
    """该章节数据目录里有哪些 NPC（按文件名排序）。没有目录就是空。"""
    if not SAFE_ID.match(chapter_id):
        return ()
    folder = DATA_DIR / chapter_id
    if not folder.is_dir():
        return ()
    return tuple(sorted(path.stem for path in folder.glob("*.json") if SAFE_ID.match(path.stem)))


def load_dialogue(chapter_id=DEFAULT_CHAPTER, npc_id=DEFAULT_NPC):
    """读取并校验某个 NPC 的对话数据（进程内缓存；改完重启服务即生效）。"""
    key = (chapter_id, npc_id)
    if key in _cache:
        return _cache[key]

    # 先查目录：不存在的 NPC 是 404（"此处没有这个人"），
    # 文件存在但读不出来才是 500（"数据有问题"）。两者不能混，否则作者改坏
    # 一个文件会看到 404，误以为是自己记错了 npcId。
    if npc_id not in npcs_for(chapter_id):
        raise ApiError("npc_not_found", "此处没有可以对话的人。", 404)

    try:
        raw = _data_path(chapter_id, npc_id).read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiError("dialogue_unavailable", "对话数据无法读取，请联系维护人员。", 500) from exc
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ApiError("dialogue_unavailable", "对话数据不是合法的 JSON，请检查格式。", 500) from exc
    _cache[key] = validate(parsed)
    return _cache[key]


def entry_node(data, quest):
    """按任务状态选入口节点；没有对应状态就用 default 兜底。"""
    entry = data["entry"]
    return entry.get(quest) or entry["default"]


def _speaker(data):
    npc = data["npc"]
    return {field: npc.get(field, "") for field in SPEAKER_FIELDS}


def _visible(when, context):
    """`when` 的求值。没有 when 就是永远可见；三类条件之间是 AND。"""
    if not when:
        return True

    states = when.get("quest")
    if states is not None:
        allowed = (states,) if isinstance(states, str) else tuple(states)
        if context["quest"] not in allowed:
            return False

    flags = when.get("flags")
    if flags:
        have = context["flags"] or {}
        for flag, wanted in flags.items():
            if bool(have.get(flag)) != wanted:
                return False

    cleared = when.get("cleared")
    if cleared:
        have = set(context["cleared"])
        if any(item not in have for item in cleared):
            return False

    return True


def build_pages(data, start, context=None):
    """把 start 起的 next 链拍平成 pages。

    两条规则，都是为了"条件不满足的内容不下发"：
    1. `when` 不满足的节点**整段跳过**，顺着它自己的 next 继续找下一段；
    2. 带 `choices` 的节点是链的终点——选项之后就停，后面的台词一律不返回。
    """
    context = context or {"quest": None, "flags": {}, "cleared": ()}
    nodes = data["nodes"]
    pages, seen, current = [], set(), start
    while current is not None:
        _require(current not in seen, f"节点 {current} 的 next 链成环")
        seen.add(current)
        node = nodes[current]

        if not _visible(node.get("when"), context):
            current = node.get("next")
            continue

        page = {"nodeId": current, "lines": list(node["lines"])}
        choices = node.get("choices")
        if choices:
            # 选项也可以带 when：同一个终点按任务状态给出不同的选项，
            # 不满足条件的选项同样不下发（否则等于告诉玩家"本来还能那样"）。
            visible = [choice for choice in choices if _visible(choice.get("when"), context)]
            if visible:
                page["choices"] = [
                    dict({"id": choice["id"], "text": choice["text"], "command": choice["command"]})
                    if choice.get("command") else {"id": choice["id"], "text": choice["text"]}
                    for choice in visible
                ]
            pages.append(page)
            break
        pages.append(page)
        current = node.get("next")
    return pages


def dialogue_for(quest, *, chapter_id=DEFAULT_CHAPTER, npc_id=DEFAULT_NPC, flags=None, cleared=()):
    """按任务状态给出完整对话对象，直接写进章节 state。

    `flags` / `cleared` 是条件选句要用的上下文：前者是章节级故事旗标，
    后者是"已经办成的事"（章节自己决定往里放什么，对话层只做判断）。
    """
    data = load_dialogue(chapter_id, npc_id)
    context = {"quest": quest, "flags": flags or {}, "cleared": tuple(cleared)}
    pages = build_pages(data, entry_node(data, quest), context)
    if not pages:
        # 一个 NPC 在当前进度下一句话都没有，是内容配置问题，不是玩家的问题。
        _fail(f"{npc_id} 在状态 {quest} 下没有任何可见台词（检查 when 是否把所有分支都挡住了）")
    return {"npcId": data["npc"]["id"], "speaker": _speaker(data), "pages": pages}


def quest_meta(chapter_id=DEFAULT_CHAPTER, npc_id=DEFAULT_NPC):
    """任务栏需要的静态文案。

    只返回文案与步骤类型，不返回任何进度：勾选状态由前端按存档推导，
    否则同一件事会有两份状态，迟早对不上。
    """
    quest = load_dialogue(chapter_id, npc_id)["quest"]
    return {
        "title": quest["title"],
        "objective": quest["objective"],
        "route": quest["route"],
        "steps": [{"kind": step["kind"], "text": step["text"]} for step in quest["steps"]],
    }


def presentation(chapter_id=DEFAULT_CHAPTER, npc_id=DEFAULT_NPC):
    """全屏剧情页的静态布景：落款、背景、演完后的去处。

    与 dialogue_for 分开：那个进存档，这个只进模板，所以不必每次 talk 都写一遍。
    """
    data = load_dialogue(chapter_id, npc_id)
    return {
        "episode": dict(data["episode"]),
        "background": data["background"],
        "then": dict(data["then"]),
        "npc": _speaker(data),
        "npcId": data["npc"]["id"],
        # 前端启动对话时要带的字段（多 NPC 章节是 {"npcId": ...}）。
        "talkFields": dict(data.get("talkFields", {})),
    }


def accepts_task(dialogue):
    """当前对话的末页是否提供了接任务选项。

    这是 accept 的前置判据：把「点一个按钮就能接任务」改成「必须真的走到
    对话末尾那个选项」，客户端无法绕过。
    """
    if not isinstance(dialogue, dict):
        return False
    pages = dialogue.get("pages")
    if not isinstance(pages, list) or not pages:
        return False
    for choice in pages[-1].get("choices") or []:
        if (choice.get("command") or {}).get("action") == "accept":
            return True
    return False
