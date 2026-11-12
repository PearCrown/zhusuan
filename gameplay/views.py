import csv
from io import StringIO
from django.http import Http404, HttpResponse
from django.db.models import Sum
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from accounts.authentication import login_required_api, login_required_page
from accounts.rate_limits import consume_limit
from accounts.views import limited_response
from classrooms.access import authorized_class, EXPORT_SCORES
from classrooms.views import page_number, paginate, csv_cell
from accounts.models import User
from core.api import ApiError, api_endpoint, api_methods, requires_json_body, read_json, success
from .chapters import REGISTRY, get_chapter
from .models import ChapterProgress
from .services import get_progress, serialize, context_for, apply_action
from .question_bank import public_questions, get_circuit_puzzle, list_circuit_puzzles, grade_circuit_solution
from . import achievements as achievements_module
from classrooms.models import StudentEnrollment
from .story import load_story
from .dialogue import presentation, quest_meta
from .catalog import load_catalog
from .skin import resolve_skin

MAX_EXPORT_ROWS = 2000


HUB_URL = "/game/#stage-select"
CAMP_URL = "/game/#camp"


@login_required_page
@never_cache
@require_safe
def workspace(request):
    return render(request, "game.html")


PROFILE_CHAPTER = "xia-circuit"


def _profile_context(user):
    """学生战绩页的数据：电路与代码两章合在一起统计。

    只有既计分又有存档结构的章节才进统计；剧情章（grade 为 None）不计分，
    只出现在云端存档页里。
    """
    scoring = [("xia-circuit", "电路工坊"), ("xia-code", "铸言")]
    rows_by_user = {row.chapter_id: row for row in ChapterProgress.objects.filter(
        user=user, chapter_id__in=[cid for cid, _ in scoring],
    )}

    passed_rows, achievements_entries, earned, attempts = [], [], 0, 0
    puzzles = list_circuit_puzzles()

    for chapter_id, chapter_title in scoring:
        progress = rows_by_user.get(chapter_id)
        state = (progress.state if progress else {}) or {}
        result = None
        if progress and progress.score is not None and progress.submitted_at:
            result = {"score": progress.score, "maxScore": 100, "submittedAt": progress.submitted_at}
            earned += progress.score

        if chapter_id == "xia-circuit":
            circuit = state.get("circuit") or {}
            levels = circuit.get("levels") or {}
            attempts += len(circuit.get("attempts") or [])
            for index, puzzle in enumerate(puzzles, start=1):
                level = levels.get(puzzle["id"]) or {}
                if level.get("passed"):
                    passed_rows.append({"index": index, "id": puzzle["id"], "chapter": chapter_title,
                                        "title": puzzle["title"], "points": level.get("points") or 0})
            achievements_entries.append((circuit, result))
        else:
            code = state.get("code") or {}
            attempts += int(code.get("attempts") or 0)
            if code.get("passed"):
                passed_rows.append({"index": len(passed_rows) + 1, "id": "xia-code", "chapter": chapter_title,
                                    "title": "铸言 · 与非的真值", "points": code.get("points") or 0})
            achievements_entries.append((code, result))

    total_items = len(puzzles) + 1          # 电路全部关卡 + 代码题

    # 排名只在同班内比较：跨班比成绩没有教学意义，也容易泄露别的班的数据。
    enrollment = StudentEnrollment.objects.filter(student=user, classroom__is_active=True).select_related("classroom").first()
    classroom = enrollment.classroom if enrollment else None
    leaderboard, rank, class_size = [], None, 0
    if classroom:
        totals = list(ChapterProgress.objects.filter(
            chapter_id__in=[cid for cid, _ in scoring], submission_class=classroom, score__isnull=False,
        ).values("user_id").annotate(total=Sum("score")).order_by("-total"))
        class_size = len(totals)
        for position, row in enumerate(totals, start=1):
            if row["user_id"] == user.pk:
                rank = position
        names = dict(User.objects.filter(pk__in=[row["user_id"] for row in totals]).values_list("pk", "display_name"))
        for position, row in enumerate(totals[:10], start=1):
            leaderboard.append({
                "rank": position,
                "name": names.get(row["user_id"], ""),
                "score": row["total"],
                "isMe": row["user_id"] == user.pk,
            })

    return {
        "classroom": classroom,
        "stats": {
            "cleared": len(passed_rows),
            "total": total_items,
            "bestScore": earned,
            "maxScore": 100 * len(scoring),
            "attempts": attempts,
            "rank": rank,
            "classSize": class_size,
        },
        "passed": passed_rows,
        "achievements": achievements_module.evaluate_many(achievements_entries),
        "leaderboard": leaderboard,
    }


def _save_summary(chapter, progress):
    """把一章的存档压成一行摘要：状态、成绩、里面到底存了什么。"""
    if progress is None:
        return {"status": "未开始", "score": None, "detail": "还没有存档。", "submittedAt": None}
    state = progress.state or {}
    if chapter.id == "xia-circuit":
        circuit = state.get("circuit") or {}
        levels = circuit.get("levels") or {}
        passed = sum(1 for level in levels.values() if level.get("passed"))
        total = len(list_circuit_puzzles())
        detail = f"电路存档：已通 {passed} / {total} 关，结算尝试 {len(circuit.get('attempts') or [])} 次"
    elif chapter.id == "xia-code":
        code = state.get("code") or {}
        source = (code.get("source") or "").strip()
        preview = source if len(source) <= 40 else source[:40] + "…"
        detail = f"代码存档：{preview}" if source else "代码存档：还没有写过表达式"
    elif chapter.id == "xia-court":
        npcs = state.get("npcs") or {}
        detail = f"剧情存档：与 {len(npcs)} 位人物对过话"
    else:
        story = state.get("story") or {}
        labels = {"not_started": "未接任务", "accepted": "任务进行中", "submitted": "任务已交付"}
        detail = f"剧情存档：{labels.get(story.get('quest'), '—')}"
    status = "已结算" if progress.submitted_at else "进行中"
    return {"status": status, "score": progress.score, "detail": detail, "submittedAt": progress.submitted_at}


@login_required_page
@never_cache
@require_safe
def saves_page(request):
    """云端存档：列出每一章在服务器上的存档状态与内容摘要。"""
    rows = []
    for chapter in REGISTRY.values():
        progress = ChapterProgress.objects.filter(user=request.user, chapter_id=chapter.id).first()
        rows.append({"id": chapter.id, "title": chapter.title, **_save_summary(chapter, progress)})
    return render(request, "saves.html", {"rows": rows})


@login_required_page
@never_cache
@require_safe
def code_page(request):
    """铸言：最小代码题页面。判分和存档都在服务端，页面只是一个编辑器。"""
    return render(request, "code.html")


@login_required_page
@never_cache
@require_safe
def profile_page(request):
    """战绩页：完成题目数、排名、通过的题目、成就与班级排行。"""
    return render(request, "profile.html", _profile_context(request.user))


@login_required_page
@never_cache
@require_safe
def circuit_page(request):
    return _render_circuit(request)


def _render_circuit(request, puzzle_id=""):
    skin = resolve_skin()
    from_camp = bool(puzzle_id) and request.GET.get("from") == "camp"
    return render(request, "circuit.html", {
        "skin": skin, "ui": skin["ui"], "initial_puzzle": puzzle_id,
        "return_url": CAMP_URL if from_camp else HUB_URL,
        "return_label": "返回营前" if from_camp else "返回关卡选择",
        "quest": {
            "title": "铸铜工坊 · 验符",
            "route": "main",
            "objective": "让已发布关卡的电路通过验算，再结算并提交工数。",
            "steps": [
                {"kind": "answers", "text": "通过电路验算"},
                {"kind": "submit", "text": "提交工数"},
            ],
        },
    })


@login_required_page
@never_cache
@require_safe
def level_page(request, level_id):
    """关卡页。当前关卡就是电路工坊，level_id 指向一个电路谜题。

    与 /game/circuit 共用同一个模板，只是把「从哪一关进来」传下去——
    这样剧情演完的「前往关卡」能直接落在对应的那一关上。
    """
    # 只认已发布的关卡：未发布的谜题在列表和详情里都看不见了，
    # 关卡页若还能直开，等于给演示留了一个"点进去没分"的死入口。
    if level_id not in {item["id"] for item in list_circuit_puzzles()}:
        raise Http404("关卡不存在。")
    try:
        puzzle = get_circuit_puzzle(level_id)
    except ApiError as error:
        raise Http404("关卡不存在。") from error
    return _render_circuit(request, puzzle["id"])


def _safe_local(url, fallback):
    """只接受站内相对路径，挡掉 //evil.com 和 http:// 这类外部跳转。"""
    if (isinstance(url, str) and url.startswith("/") and not url.startswith("//")
            and url_has_allowed_host_and_scheme(url, allowed_hosts=None)):
        return url
    return fallback


def get_chapter_or_404(chapter_id):
    """页面视图里章节不存在应该是 404，而不是把 ApiError 抛成 500。"""
    try:
        return get_chapter(chapter_id)
    except ApiError as error:
        raise Http404("章节不存在。") from error


@login_required_page
@never_cache
@require_safe
def story_page(request, chapter_id, npc_id):
    """全屏剧情页。宿主（大地图/章节小地图）只需跳到这里。

    两个可选查询参数，构成对 A 的地图接口：
      next=<站内路径>  演完后「进入关卡」跳到哪（默认取数据里的 then.url）
      back=<站内路径>  「返回」按钮回到哪（默认 /game/）
    """
    chapter = get_chapter_or_404(chapter_id)
    # 对话按 (chapterId, npcId) 取：一个章节可以有多个 NPC，各有一份数据。
    # 不存在的 NPC 是 404，与"章节不存在"同一个口径。
    try:
        stage = presentation(chapter_id, npc_id)
        quest = quest_meta(chapter_id, npc_id)
    except ApiError as error:
        raise Http404("此处没有可以对话的人。") from error
    return render(request, "story.html", {
        "stage": stage,
        "chapter": chapter,
        "chapter_id": chapter_id,
        "npc_id": npc_id,
        "next_url": _safe_local(request.GET.get("next"), stage["then"]["url"]),
        "back_url": _safe_local(request.GET.get("back"), CAMP_URL if chapter_id == "xia-court" else "/game/"),
        # 剧情页角落的精简任务栏用同一份文案，接任务后才出现。
        "quest": quest,
    })


@login_required_api
@api_methods("GET", "HEAD")
def chapters(request):
    if request.GET:
        raise ApiError("invalid_query", "此接口不接受查询参数。")
    return success({"chapters": [{"chapterId": c.id, "title": c.title, "schemaVersion": c.schema_version, "kind": c.kind} for c in REGISTRY.values()]})


@login_required_api
@api_methods("GET", "HEAD")
def progress(request, chapter_id):
    if request.GET:
        raise ApiError("invalid_query", "此接口不接受查询参数。")
    chapter = get_chapter(chapter_id)
    saved = get_progress(request.account_user, chapter)
    bank_id = saved.question_bank_id if saved else chapter.question_bank_id
    bank_version = saved.question_bank_version if saved else chapter.question_bank_version
    return success({"saveContext": context_for(request, chapter, saved), "progress": serialize(saved, chapter),
        "questions": public_questions(bank_id, bank_version) if bank_id else []})


@login_required_api
@requires_json_body
@api_methods("POST")
def action(request, chapter_id):
    chapter = get_chapter(chapter_id)
    blocked = limited_response(consume_limit("game_action_user", str(request.account_user.pk), window=60, limit=120))
    if blocked is not None:
        return blocked
    if request.GET:
        raise ApiError("invalid_query", "此接口不接受查询参数。")
    state = apply_action(request, chapter, read_json(request))
    return success({"saveContext": context_for(request, chapter, state), "progress": serialize(state, chapter)})


def score_data(row):
    return {"userId": str(row.user_id), "username": row.user.username, "displayName": row.user.display_name,
        "chapterId": row.chapter_id, "score": row.score, "maxScore": 100, "submittedAt": row.submitted_at.isoformat(),
        "questionBank": {"bankId": row.question_bank_id, "version": row.question_bank_version}}


def class_scores(classroom):
    return ChapterProgress.objects.filter(submission_class=classroom, submitted_at__isnull=False, score__isnull=False).select_related("user").order_by("user_id", "chapter_id")


@login_required_api
@api_methods("GET", "HEAD")
def teacher_scores(request, class_id):
    classroom = authorized_class(request.account_user, class_id)
    return success({"className": classroom.name, **paginate(class_scores(classroom), page_number(request), score_data)})


@login_required_api
@api_methods("GET", "HEAD")
def teacher_scores_csv(request, class_id):
    classroom = authorized_class(request.account_user, class_id, action=EXPORT_SCORES)
    page_number(request, allow_page=False)
    rows = list(class_scores(classroom)[:MAX_EXPORT_ROWS + 1])
    if len(rows) > MAX_EXPORT_ROWS:
        raise ApiError("export_too_large", "成绩超过单次2000条导出上限。", 413)
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["用户编号", "用户名", "显示名称", "章节", "成绩", "满分", "提交时间", "题库", "题库版本"])
    for row in rows:
        data = score_data(row)
        writer.writerow([csv_cell(data[key]) for key in ["userId", "username", "displayName", "chapterId", "score", "maxScore", "submittedAt"]] + [csv_cell(data["questionBank"][key]) for key in ["bankId", "version"]])
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="class-{classroom.pk}-scores.csv"'
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# ---- 电路谜题（Turing Complete 风格） ----

@login_required_api
@never_cache
@require_safe
@api_methods("GET", "HEAD")
def circuit_story(request):
    """剧情与关卡委托。纯数据，改文案不需要动代码。"""
    if request.GET:
        raise ApiError("invalid_query", "此接口不接受查询参数。")
    return success({"story": load_story(), "catalog": load_catalog()})



MAX_CIRCUIT_GATES = 200
MAX_CIRCUIT_WIRES = 400


@api_endpoint
@never_cache
@require_safe
@api_methods("GET", "HEAD")
def circuit_puzzles(request):
    return success({"puzzles": list_circuit_puzzles()})


@api_endpoint
@never_cache
@require_safe
@api_methods("GET", "HEAD")
def circuit_puzzle(request, puzzle_id):
    # 未发布的关卡不该还能直开详情：列表里看不到、结算也提交不了，
    # 但按 id 直接访问仍然拿得到，等于把"看得到做不了"换了个入口。
    released = {item["id"] for item in list_circuit_puzzles()}
    if puzzle_id not in released:
        raise ApiError("puzzle_not_found", "谜题暂不可用。", 404)
    return success({"puzzle": get_circuit_puzzle(puzzle_id)})


@login_required_api
@requires_json_body
@api_methods("POST")
def circuit_grade(request, puzzle_id):
    body = read_json(request)
    gates = body.get("gates", [])
    wires = body.get("wires", [])
    if not isinstance(gates, list) or not isinstance(wires, list):
        raise ApiError("validation_error", "电路数据格式不正确。")
    if len(gates) > MAX_CIRCUIT_GATES or len(wires) > MAX_CIRCUIT_WIRES:
        raise ApiError("validation_error", "电路规模超出限制。")
    result = grade_circuit_solution(puzzle_id, gates, wires)
    return success(result)
