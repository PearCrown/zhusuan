"""把电路工坊接入章节插件接口。

在此之前，电路关卡的判分走独立端点 /game/api/circuit/puzzles/<id>/grade：
它把结果返回给浏览器，不写任何表。后果是教师端永远看不到学生玩过电路，
而老师点名要的「示例关卡证明接口可用」也无从谈起——真正有教学价值的玩法
恰好挂在接口之外。

这里把五个电路谜题注册成一个正式章节，解锁、乐观锁存档、成绩回传、
教师端可见全部复用同一条既有链路，不再存在第二条判分口径。
一章五关，每关 20 分，合计 100。

结算语义：`settle` 是一次「结算尝试」——判分并往 circuit.attempts 追加一条记录，
不通过就把章节留在未结算状态，玩家可以继续做工再来；只有达到通过线的那次尝试
才允许随后调 `submit` 真正写成绩。这样失败的尝试天然可重试，而成绩仍然只有一份，
不重复结算（`services.apply_action` 对已提交章节的幂等语义一行未改）。

交付方式由剧情数据里的 deliver 声明，本模块目前只支持 auto（关卡页即结算）；
npc 交付（回 NPC 对话交付）属于 sample-counting 那条线。
"""

from copy import deepcopy

from django.utils import timezone

from core.api import ApiError

from . import question_bank, rewards
from .chapters import Chapter, register
from .circuit_sim import GATE_TYPES
from .story import deliver_mode, level_reward

CHAPTER_ID = "xia-circuit"
BANK_ID = "circuit-levels"
BANK_VERSION = "1"

MAX_GATES = 200
MAX_WIRES = 400

# 通过线。五关各 20 分，满分 100 才算通过。暂定值：改这一行就是改通过线。
PASS_SCORE = 100


def initial_state(bank_id, bank_version):
    puzzle_ids = question_bank.get_circuit_release(bank_id, bank_version)
    # attempts / pendingSettle 只增不改：老存档没有这两个键时按「没有尝试记录、
    # 没有待结算的通过」处理，所以不必升 schema_version，也不会卡住老玩家。
    # rewards 是奖励账本（见 gameplay/rewards.py）：同样只增不改，
    # 老存档没有这个键时由 rewards.ledger() 就地补建。
    return {"circuit": {"levels": {}, "solvedOrder": [], "puzzleIds": list(puzzle_ids),
                        "attempts": [], "pendingSettle": False},
            "rewards": {}}


def _coerce_position(value):
    """位置只用于存档还原，非法值丢弃而不是让整次提交失败。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return int(value)


def _sanitize_gates(gates):
    cleaned = []
    for gate in gates:
        if not isinstance(gate, dict):
            raise ApiError("validation_error", "电路元件格式不正确。")
        gate_id, gate_type = gate.get("id"), gate.get("type")
        if not isinstance(gate_id, str) or not gate_id or gate_type not in GATE_TYPES:
            raise ApiError("validation_error", "电路元件格式不正确。")
        entry = {"id": gate_id, "type": gate_type}
        x, y = _coerce_position(gate.get("x")), _coerce_position(gate.get("y"))
        if x is not None and y is not None:
            entry["x"], entry["y"] = x, y
        cleaned.append(entry)
    return cleaned


def _sanitize_wires(wires):
    cleaned = []
    for wire in wires:
        if not isinstance(wire, dict):
            raise ApiError("validation_error", "连线格式不正确。")
        ends = []
        for key in ("from", "to"):
            end = wire.get(key)
            if not isinstance(end, dict):
                raise ApiError("validation_error", "连线格式不正确。")
            gate_id, port = end.get("gateId"), end.get("port")
            if not isinstance(gate_id, str) or not gate_id or not isinstance(port, str) or not port:
                raise ApiError("validation_error", "连线格式不正确。")
            ends.append({"gateId": gate_id, "port": port})
        cleaned.append({"from": ends[0], "to": ends[1]})
    return cleaned


def _level(circuit, puzzle_id):
    levels = circuit["levels"]
    if puzzle_id not in levels:
        levels[puzzle_id] = {"passed": False, "points": 0, "attempts": 0}
    return levels[puzzle_id]


def _require_auto_delivery():
    """电路章节目前只支持 auto 交付（关卡页即结算）。

    npc 交付需要 NPC 与交付对话，那属于 sample-counting 那条线。
    配置写错却看起来「能用」是最难查的故障，所以这里当场响亮报错。
    """
    mode = deliver_mode()
    if mode != "auto":
        raise ApiError("delivery_unsupported", f"电路章节目前只支持 auto 交付，收到 deliver={mode}。", 500)


def transition(state, action, payload):
    state = deepcopy(state)
    circuit = state["circuit"]

    if action == "solve":
        puzzle_id = payload.get("puzzleId")
        if not isinstance(puzzle_id, str) or puzzle_id not in circuit["puzzleIds"]:
            raise ApiError("puzzle_not_found", "谜题暂不可用。", 404)
        gates, wires = payload.get("gates"), payload.get("wires")
        if not isinstance(gates, list) or not isinstance(wires, list):
            raise ApiError("validation_error", "电路数据格式不正确。")
        if len(gates) > MAX_GATES or len(wires) > MAX_WIRES:
            raise ApiError("validation_error", "电路规模超出限制。")
        gates, wires = _sanitize_gates(gates), _sanitize_wires(wires)

        # 关卡允许的元件此前只用于前端调色板，服务端并不执行。
        # 于是「本关只准用 NAND」形同虚设：直接摆一个 AND 门也能通过真值表。
        puzzle = question_bank.get_circuit_puzzle(puzzle_id)
        allowed = set(puzzle["components"])
        forbidden = sorted({gate["type"] for gate in gates if gate["type"] not in allowed})
        if forbidden:
            raise ApiError("invalid_component", f"本关不允许使用 {'、'.join(forbidden)}。")

        # 判分只由服务端仿真产生，客户端提交的只是电路本身。
        result = question_bank.grade_circuit_solution(puzzle_id, gates, wires)
        level = _level(circuit, puzzle_id)
        level["attempts"] += 1
        # 把这次逐行结果一并存档，前端就不必再单独请求一次判分，
        # 也保证"学生看到的反馈"和"成绩库里的结论"出自同一次计算。
        level["lastResult"] = {"passed": result["passed"], "points": result["points"], "cases": result["cases"]}
        if result["passed"] and not level["passed"]:
            level["passed"] = True
            level["points"] = result["points"]
            # 通关的电路留存下来，这就是老师要求的"电路存档"。
            level["gates"] = gates
            level["wires"] = wires
            circuit["solvedOrder"].append(puzzle_id)
        if result["passed"]:
            # 通关奖励：每次通过都来这里报到，由账本决定发不发——重玩同一关
            # 第二次只会留下 lastAttemptAt，不会重复发（见 gameplay/rewards.py）。
            reward_id = level_reward(puzzle_id)
            if reward_id:
                rewards.grant(state, reward_id, at=timezone.now().isoformat(timespec="seconds"))
        return state

    if action == "settle":
        # 一次结算尝试：判分、留档，但只有达到通过线才允许随后真正结算。
        # 不通过就停在这里——关卡记录原样保留，玩家可以接着做工，再来一次。
        _require_auto_delivery()
        if circuit.get("pendingSettle"):
            raise ApiError("settle_pending", "这次尝试已通过，请先完成结算。", 409)
        score = grade(state)
        passed = score >= PASS_SCORE
        attempts = circuit.setdefault("attempts", [])
        attempts.append({
            "n": len(attempts) + 1,
            "score": score,
            "maxScore": 100,
            "passed": passed,
            "at": timezone.now().isoformat(timespec="seconds"),
        })
        circuit["pendingSettle"] = passed
        return state

    if action == "submit":
        # 结算：只有刚通过的那次尝试可以结算，而且成绩只写这一次。
        # 前置条件在服务端判定，客户端连点也绕不过去。
        if not circuit.get("pendingSettle"):
            raise ApiError("invalid_transition", "本章还没有通过结算尝试，不能结算成绩。", 409)
        # 结算完成后清掉标记：之后的重复提交走"幂等返回原成绩"，
        # 而不是被当成一次新的重做提交。
        circuit["pendingSettle"] = False
        return state

    raise ApiError("invalid_action", "不支持此章节操作。")


def grade(state):
    return sum(level["points"] for level in state["circuit"]["levels"].values())


register(Chapter(
    CHAPTER_ID,
    "铸算·夏 · 电路工坊",
    1,
    initial_state,
    transition,
    grade,
    {"solve": {"puzzleId", "gates", "wires"}, "settle": set(), "submit": set()},
    BANK_ID,
    BANK_VERSION,
    "circuit",
    replay=True,
    # 只有"刚通过一次、还没结算"的存档才算新的重做提交，其余重复提交保持幂等。
    pending_resubmit=lambda state: bool(((state or {}).get("circuit") or {}).get("pendingSettle")),
))
