"""Trusted server plugins only. No user uploads, dynamic code or remote scripts."""
from copy import deepcopy
from dataclasses import dataclass
from core.api import ApiError
from . import question_bank


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
    return {"story": {"scene": "gate", "talkedToNpc": False, "quest": "not_started"},
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
    elif action == "talk":
        if story["scene"] != "gate":
            raise invalid()
        story["talkedToNpc"] = True
    elif action == "accept":
        if story["scene"] != "gate" or not story["talkedToNpc"] or story["quest"] != "not_started":
            raise invalid()
        story["quest"] = "accepted"
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
