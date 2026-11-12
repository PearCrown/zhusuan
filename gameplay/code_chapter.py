"""最小代码题章节：用布尔表达式写出「与非」，服务端判分并存档源码。

为什么不做真正的 Python 执行：
用户写的代码在本机 exec/eval 等于把服务器交出去。这里只接受一棵极小的
表达式树（变量 a、b + and/or/not + 括号），自己遍历求值，既不执行任意代码，
又能让学生真切地“写一行代码、看它跑出真值表”。

存档里保留学生最后提交的源码，这就是“代码存档”。
"""
import ast

from core.api import ApiError
from .chapters import Chapter, register

CHAPTER_ID = "xia-code"
# 代码题没有题库：判分靠本章自己的真值表，所以不挂题库 id。
# 留空可以让 /progress 跳过 public_questions（否则会去查一个不存在的题库版本）。
BANK_ID = ""
BANK_VERSION = ""
MAX_SOURCE = 500

# 与非真值表：a b -> out
TRUTH_TABLE = [
    (0, 0, 1),
    (0, 1, 1),
    (1, 0, 1),
    (1, 1, 0),
]

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Name, ast.Load,
    ast.And, ast.Or, ast.Not, ast.Constant, ast.operator,
)


def _parse(source):
    if not isinstance(source, str):
        raise ApiError("validation_error", "代码必须是文本。")
    if not source.strip():
        raise ApiError("validation_error", "先写一行表达式再运行。")
    if len(source) > MAX_SOURCE:
        raise ApiError("validation_error", f"代码不能超过 {MAX_SOURCE} 个字符。")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as error:
        raise ApiError("syntax_error", f"语法错误：第 {error.lineno or '?'} 行附近写错了。") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ApiError(
                "forbidden_node",
                "这里只支持变量 a、b，以及 and / or / not 和括号；不支持函数调用、赋值或其他语句。",
            )
    return tree


def _evaluate(node, env):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, env)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ApiError("unknown_name", f"变量 {node.id} 不存在，只能用 a 和 b。")
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _evaluate(node.operand, env)
    if isinstance(node, ast.BoolOp):
        values = [_evaluate(value, env) for value in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Constant) and node.value in (0, 1, True, False):
        return bool(node.value)
    raise ApiError("forbidden_node", "表达式里有无法求值的部分。")


def judge(source):
    """返回 {passed, rows, message}；行与行之间与学生看到的一致。"""
    tree = _parse(source)
    rows, failed = [], 0
    for a, b, expected in TRUTH_TABLE:
        actual = 1 if _evaluate(tree, {"a": bool(a), "b": bool(b)}) else 0
        ok = actual == expected
        failed += 0 if ok else 1
        rows.append({"inputs": [a, b], "expected": expected, "actual": actual, "pass": ok})
    return {
        "passed": failed == 0,
        "rows": rows,
        "message": "四行真值表全部吻合。" if failed == 0 else f"有 {failed} 行对不上。",
    }


def initial_state(bank_id, bank_version):
    return {"code": {"source": "", "passed": False, "points": 0, "attempts": 0, "rows": []}}


def transition(state, action, payload):
    code = state.setdefault("code", {"source": "", "passed": False, "points": 0, "attempts": 0, "rows": []})
    if action == "solve":
        result = judge(payload.get("source"))
        code["source"] = payload.get("source") or ""
        code["attempts"] = int(code.get("attempts") or 0) + 1
        code["rows"] = result["rows"]
        if result["passed"]:
            code["passed"] = True
            code["points"] = 100
        return state
    if action == "submit":
        if not code.get("passed"):
            raise ApiError("invalid_transition", "还没有通过，先让四行真值表全对。", 409)
        return state
    raise ApiError("invalid_action", "不支持的章节操作。")


def grade(state):
    code = (state or {}).get("code") or {}
    return 100 if code.get("passed") else 0


register(Chapter(
    CHAPTER_ID,
    "铸算·夏 · 铸言",
    1,
    initial_state,
    transition,
    grade,
    {"solve": {"source"}, "submit": set()},
    BANK_ID,
    BANK_VERSION,
    "code",
    # 可重做：改一行再跑，成绩取最高，代码本身也留在存档里。
    replay=True,
    pending_resubmit=lambda state: bool(((state or {}).get("code") or {}).get("passed")),
))
