"""Trusted server plugins only. No user uploads, dynamic code or remote scripts."""
from copy import deepcopy
from dataclasses import dataclass
from core.api import ApiError
from . import question_bank
from .dialogue import accepts_task, dialogue_for


@dataclass(frozen=True)
class Chapter:
    id: str
    title: str
    schema_version: int
    initial_state: object
    transition: object
    grade: object
    actions: dict
    question_bank_id: str = ""
    question_bank_version: str = ""
    kind: str = "story"
    # 已结算后是否还能继续练习。开启后成绩只取历史最高，重做不会把分数改小。
    replay: bool = False
    # 可重做章节用它判断"这次提交是否带着一次新的通过尝试"，
    # 没有新尝试的重复提交仍然幂等返回已记录的成绩。
    pending_resubmit: object = None


REGISTRY = {}


def register(chapter):
    if chapter.id in REGISTRY:
        raise ValueError("Duplicate chapter registration")
    REGISTRY[chapter.id] = chapter


def get_chapter(chapter_id):
    if chapter_id not in REGISTRY:
        raise ApiError("chapter_not_found", "章节不存在。", 404)
    return REGISTRY[chapter_id]


def initial_state(bank_id, bank_version):
    questions = question_bank.get_release(bank_id, bank_version)
    # dialogue 是"当前打开的对话"快照，由 talk 动作按任务状态重算。
    # 它只增不改，老存档没有这个键时一律按 None 处理，因此不必升 schema_version。
    return {"story": {"scene": "gate", "talkedToNpc": False, "quest": "not_started", "dialogue": None},
        "practice": {"bankId": bank_id, "bankVersion": bank_version, "answers": [None] * len(questions)}}


def invalid():
    return ApiError("invalid_transition", "当前不能执行这一步，请按章节提示操作。", 409)


def transition(state, action, payload):
    state = deepcopy(state)
    story, practice = state["story"], state["practice"]
    if action == "move":
        if not isinstance(payload.get("scene"), str) or payload["scene"] not in {"gate", "workshop"}:
            raise ApiError("validation_error", "场景无效。")
        story["scene"] = payload["scene"]
        # 离开场景时收起对话，否则回来会看到上一个场景的台词。
        story["dialogue"] = None
    elif action == "talk":
        if story["scene"] != "gate":
            raise invalid()
        story["talkedToNpc"] = True
        # 服务端按任务状态选入口并把 next 链拍平成 pages，一次返回。
        story["dialogue"] = dialogue_for(story["quest"])
    elif action == "accept":
        if story["scene"] != "gate" or story["quest"] != "not_started":
            raise invalid()
        # 接任务的前提是"对话已经走到末尾那个选项"，而不是点了一个按钮。
        # 老存档没有 dialogue 键，这里天然为 False，玩家重新对话即可。
        if not accepts_task(story.get("dialogue")):
            raise ApiError("dialogue_incomplete", "请先与守门人把话说完。", 409)
        story["quest"] = "accepted"
        story["dialogue"] = dialogue_for("accepted")
    elif action == "answer":
        if story["scene"] != "workshop" or story["quest"] != "accepted":
            raise invalid()
        index, answer = payload.get("questionIndex"), payload.get("answer")
        if type(index) is not int or not 0 <= index < len(practice["answers"]) or type(answer) is not int or not 0 <= answer <= 10000:
            raise ApiError("validation_error", "题目或答案无效，请填写0至10000的整数。")
        practice["answers"][index] = answer
    elif action == "submit":
        if story["scene"] != "gate" or story["quest"] != "accepted" or any(answer is None for answer in practice["answers"]):
            raise invalid()
        story["quest"] = "submitted"
    else:
        raise ApiError("invalid_action", "不支持此章节操作。")
    return state


def grade(state):
    practice = state["practice"]
    return question_bank.grade(practice["bankId"], practice["bankVersion"], practice["answers"])


register(Chapter("sample-counting", "算坊初试 · 接入样例", 1, initial_state, transition, grade,
    {"move": {"scene"}, "talk": set(), "accept": set(), "answer": {"questionIndex", "answer"}, "submit": set()},
    "sample-arithmetic", "1", "integration_sample"))


# 电路关卡章节定义在独立模块里，导入即注册。放在文件末尾是为了让上面
# 的 Chapter/register 先定义完成，避免循环导入拿到半个模块。
from . import circuit_chapter  # noqa: E402,F401
from . import court_chapter  # noqa: E402,F401
from . import code_chapter  # noqa: E402,F401
