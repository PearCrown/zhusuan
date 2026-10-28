import csv
from io import StringIO
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from accounts.authentication import login_required_api
from accounts.rate_limits import consume_limit
from accounts.views import limited_response
from classrooms.access import authorized_class, EXPORT_SCORES
from classrooms.views import page_number, paginate, csv_cell
from core.api import ApiError, api_methods, requires_json_body, read_json, success
from .chapters import REGISTRY, get_chapter
from .models import ChapterProgress
from .services import get_progress, serialize, context_for, apply_action
from .question_bank import public_questions

MAX_EXPORT_ROWS = 2000


@never_cache
@require_safe
def workspace(request):
    return render(request, "game.html")


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
