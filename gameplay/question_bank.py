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
# 电路关卡不用固定答案判分，而是由服务端仿真求值，因此单独登记版本。
# 登记时校验总分恰好 100，避免以后调整某个关卡的分值把整章总分搞乱。
CIRCUIT_RELEASES = {}


def register_release(bank_id, version, questions):
    key = (bank_id, version)
    if key in RELEASES:
        raise ValueError("Question releases are immutable; register a new version")
    questions = tuple(questions)
    if not questions or len({q.id for q in questions}) != len(questions) or sum(q.points for q in questions) != 100:
        raise ValueError("Invalid question release")
    RELEASES[key] = questions


def register_circuit_release(bank_id, version, puzzle_ids):
    """登记一组电路关卡作为一章的"题库"。"""
    key = (bank_id, version)
    if key in CIRCUIT_RELEASES:
        raise ValueError("Circuit releases are immutable; register a new version")
    puzzle_ids = tuple(puzzle_ids)
    if not puzzle_ids or len(set(puzzle_ids)) != len(puzzle_ids) or any(pid not in CIRCUIT_PUZZLES for pid in puzzle_ids):
        raise ValueError("Invalid circuit release")
    if sum(CIRCUIT_PUZZLES[pid]["points"] for pid in puzzle_ids) != 100:
        raise ValueError("Circuit release must total 100 points")
    CIRCUIT_RELEASES[key] = puzzle_ids


def get_circuit_release(bank_id, version):
    if (bank_id, version) not in CIRCUIT_RELEASES:
        raise ApiError("question_version_unavailable", "关卡版本暂不可用，请联系维护人员。", 409)
    return CIRCUIT_RELEASES[bank_id, version]


def get_release(bank_id, version):
    if (bank_id, version) not in RELEASES:
        raise ApiError("question_version_unavailable", "题目版本暂不可用，请联系维护人员。", 409)
    return RELEASES[bank_id, version]


def public_questions(bank_id, version):
    # 电路关卡只下发谜题摘要（另走 /game/api/circuit/puzzles），没有题目文本。
    if (bank_id, version) in CIRCUIT_RELEASES:
        return []
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

# ==============================================================================
# 电路谜题（参考 Turing Complete 玩法）
# 每道题是一个电路谜题：玩家需搭建电路实现指定真值表
# ==============================================================================
CIRCUIT_PUZZLES = {
    "tc-nand": {
        "title": "第一关：识·与非",
        "description": "「万物始于一」——仅用一个 NAND 门，完成真值表验证。\n这是所有数字电路的起点。",
        "components": ["NAND"],  # 可用组件
        "inputs": ["A", "B"],
        "outputs": ["Y"],
        "truthTable": [
            {"inputs": [0, 0], "outputs": [1]},
            {"inputs": [0, 1], "outputs": [1]},
            {"inputs": [1, 0], "outputs": [1]},
            {"inputs": [1, 1], "outputs": [0]},
        ],
        "points": 100,
    },
    "tc-and": {
        "title": "第二关：铸·与门",
        "description": "「两NAND相成，为AND门」——用两个 NAND 搭出 AND 逻辑。",
        "components": ["NAND"],
        "inputs": ["A", "B"],
        "outputs": ["Y"],
        "truthTable": [
            {"inputs": [0, 0], "outputs": [0]},
            {"inputs": [0, 1], "outputs": [0]},
            {"inputs": [1, 0], "outputs": [0]},
            {"inputs": [1, 1], "outputs": [1]},
        ],
        "points": 20,
    },
    "tc-or": {
        "title": "第三关：铸·或门",
        "description": "「或非再取反，为OR门」——用 NAND 搭出 OR 逻辑。",
        "components": ["NAND"],
        "inputs": ["A", "B"],
        "outputs": ["Y"],
        "truthTable": [
            {"inputs": [0, 0], "outputs": [0]},
            {"inputs": [0, 1], "outputs": [1]},
            {"inputs": [1, 0], "outputs": [1]},
            {"inputs": [1, 1], "outputs": [1]},
        ],
        "points": 20,
    },
    "tc-xor": {
        "title": "第四关：铸·异或",
        "description": "「异者，不同则一」——搭出 XOR，这是加法器的核心。",
        "components": ["NAND", "AND", "OR"],
        "inputs": ["A", "B"],
        "outputs": ["Y"],
        "truthTable": [
            {"inputs": [0, 0], "outputs": [0]},
            {"inputs": [0, 1], "outputs": [1]},
            {"inputs": [1, 0], "outputs": [1]},
            {"inputs": [1, 1], "outputs": [0]},
        ],
        "points": 20,
    },
    "tc-half-adder": {
        "title": "第五关：铸·半加器",
        "description": "「算者，加也」——搭建半加器，输出 SUM 与 CARRY。",
        "components": ["NAND", "AND", "OR", "XOR"],
        "inputs": ["A", "B"],
        "outputs": ["SUM", "CARRY"],
        "truthTable": [
            {"inputs": [0, 0], "outputs": [0, 0]},
            {"inputs": [0, 1], "outputs": [1, 0]},
            {"inputs": [1, 0], "outputs": [1, 0]},
            {"inputs": [1, 1], "outputs": [0, 1]},
        ],
        "points": 20,
    },
}


def get_circuit_puzzle(puzzle_id):
    """返回指定电路谜题的定义（面向前端）

    id 在 CIRCUIT_PUZZLES 里是字典的键而不是字段，但详情响应必须自带 id：
    否则调用方拿到对象后无法知道自己是哪一关，一提交就漏字段。
    """
    if puzzle_id not in CIRCUIT_PUZZLES:
        raise ApiError("puzzle_not_found", "谜题暂不可用。", 404)
    return {"id": puzzle_id, **CIRCUIT_PUZZLES[puzzle_id]}


def list_circuit_puzzles(bank_id="circuit-levels", version="1"):
    """返回本章已发布的电路谜题。

    只列发布清单里的关卡：未发布的谜题既不能做也拿不到分，
    摆在选择器里只会让人以为"看到的就是能做的"。
    """
    released = get_circuit_release(bank_id, version)
    return [{"id": pid, "title": CIRCUIT_PUZZLES[pid]["title"],
             "description": CIRCUIT_PUZZLES[pid]["description"]} for pid in released]


def grade_circuit_solution(puzzle_id, gates, wires):
    """
    对用户提交的电路进行模拟 + 真值表验证
    gates:  [{id, type, x, y}]
    wires:  [{from: {gateId, port}, to: {gateId, port}}]
    返回：{passed: bool, cases: [{inputs, expected, actual, pass}]}
    """
    from .circuit_sim import simulate  # 延迟导入避免循环
    puzzle = get_circuit_puzzle(puzzle_id)
    results = []
    all_pass = True
    for row in puzzle["truthTable"]:
        try:
            actual = simulate(puzzle, gates, wires, row["inputs"])
            ok = actual == row["outputs"]
        except Exception:
            actual = None
            ok = False
        if not ok:
            all_pass = False
        results.append({
            "inputs": row["inputs"],
            "expected": row["outputs"],
            "actual": actual,
            "pass": ok,
        })
    return {"passed": all_pass, "cases": results, "points": puzzle["points"] if all_pass else 0}

# 五个电路谜题构成「铸算·夏」一章，每关 20 分，合计 100。
# 演示章只发布第一关：五关各 20 分、通过线 100 的旧结构，单看一关永远结算不了。
# 其余四关的定义与判分保留，改回多关只要把它们加回这个清单并重算分值。
register_circuit_release("circuit-levels", "1", ("tc-nand",))
