"""Immutable exercise releases; replace this provider with a DB-backed adapter later."""
from dataclasses import dataclass
from core.api import ApiError


@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    answer: int
    points: int


RELEASES = {}


def register_release(bank_id, version, questions):
    key = (bank_id, version)
    if key in RELEASES:
        raise ValueError("Question releases are immutable; register a new version")
    questions = tuple(questions)
    if not questions or len({q.id for q in questions}) != len(questions) or sum(q.points for q in questions) != 100:
        raise ValueError("Invalid question release")
    RELEASES[key] = questions


def get_release(bank_id, version):
    if (bank_id, version) not in RELEASES:
        raise ApiError("question_version_unavailable", "题目版本暂不可用，请联系维护人员。", 409)
    return RELEASES[bank_id, version]


def public_questions(bank_id, version):
    return [{"questionId": q.id, "prompt": q.prompt} for q in get_release(bank_id, version)]


def grade(bank_id, version, answers):
    questions = get_release(bank_id, version)
    if len(answers) != len(questions):
        raise ApiError("save_version_unsupported", "答案结构不匹配，请联系维护人员。", 409)
    return sum(q.points for answer, q in zip(answers, questions) if answer == q.answer)


register_release("sample-arithmetic", "1", (
    Question("sum-2-3", "2 + 3 = ?", 5, 30),
    Question("multiply-4-3", "4 × 3 = ?", 12, 30),
    Question("sum-6-7", "6 + 7 = ?", 13, 40),
))
