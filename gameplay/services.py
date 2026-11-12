from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac, constant_time_compare

from accounts.models import User
from classrooms.models import StudentEnrollment
from core.api import ApiError
from .models import ChapterProgress


def context_for(request, chapter, progress=None):
    # This is a stale-tab guard, not a substitute for session auth or CSRF.
    user = request.account_user
    bank_id = progress.question_bank_id if progress else chapter.question_bank_id
    version = progress.question_bank_version if progress else chapter.question_bank_version
    return salted_hmac("gameplay.save_context", f"{user.pk}:{user.session_revision}:{request.session.session_key}:{chapter.id}:{chapter.schema_version}:{bank_id}:{version}", algorithm="sha256").hexdigest()


def serialize(progress, chapter):
    return {"chapterId": chapter.id, "schemaVersion": progress.schema_version if progress else chapter.schema_version,
        "revision": progress.revision if progress else 0, "state": progress.state if progress else chapter.initial_state(chapter.question_bank_id, chapter.question_bank_version),
        "questionBank": {"bankId": progress.question_bank_id if progress else chapter.question_bank_id,
            "version": progress.question_bank_version if progress else chapter.question_bank_version},
        "result": {"score": progress.score, "maxScore": 100 if progress.score is not None else None, "submittedAt": progress.submitted_at.isoformat()} if progress and progress.submitted_at else None}


def get_progress(user, chapter):
    progress = ChapterProgress.objects.filter(user_id=user.pk, chapter_id=chapter.id).first()
    if progress and progress.schema_version != chapter.schema_version:
        raise ApiError("save_version_unsupported", "存档版本需要迁移，请联系维护人员。", 409)
    return progress


@transaction.atomic
def apply_action(request, chapter, payload):
    action = payload.get("action")
    if not isinstance(action, str) or action not in chapter.actions:
        raise ApiError("invalid_action", "不支持此章节操作。")
    if set(payload) != {"action", "revision", "saveContext"} | chapter.actions[action]:
        raise ApiError("invalid_fields", "操作字段缺失或包含不支持的字段。")
    if type(payload["revision"]) is not int or not 0 <= payload["revision"] <= 9007199254740991:
        raise ApiError("validation_error", "存档版本号无效。")
    user = User.objects.select_for_update().get(pk=request.account_user.pk)
    if not user.is_active or user.session_revision != request.account_user.session_revision or user.password != request.account_user.password:
        raise ApiError("authentication_required", "登录已失效，请重新登录。", 401)
    supplied = payload["saveContext"]
    progress = get_progress(user, chapter)
    if not isinstance(supplied, str) or not constant_time_compare(supplied, context_for(request, chapter, progress)):
        raise ApiError("save_context_changed", "账号、会话或章节版本已变化，请重新载入。", 409)
    # Submission retries return the committed result, never score twice.
    if progress and progress.submitted_at:
        resubmitting = (action == "submit" and chapter.replay and chapter.pending_resubmit
                        and chapter.pending_resubmit(progress.state))
        if resubmitting:
            pass                      # 重做拿到新的通过：继续走结算，成绩只增不减
        elif action == "submit":
            return progress           # 幂等：没有新尝试时重复提交返回原成绩
        elif not chapter.replay:
            raise ApiError("chapter_completed", "本样例已完成，只能查看结果。", 409)
        # 可重做的章节：solve / settle 继续放行，只改存档不改成绩
    if payload["revision"] != (progress.revision if progress else 0):
        raise ApiError("save_conflict", "存档已更新，请重新载入后再操作。", 409)
    state = chapter.transition(progress.state if progress else chapter.initial_state(chapter.question_bank_id, chapter.question_bank_version), action, payload)
    if progress is None:
        progress = ChapterProgress(user=user, chapter_id=chapter.id, schema_version=chapter.schema_version,
            question_bank_id=chapter.question_bank_id, question_bank_version=chapter.question_bank_version)
    progress.state = state
    progress.revision += 1
    if action == "submit":
        score = chapter.grade(state) if chapter.grade else None
        if score is not None and (type(score) is not int or not 0 <= score <= 100):
            raise ValueError("Chapter returned invalid score")
        # 取历史最高：重做只在更高时改写成绩，低了保留原来的。
        # 非计分章节（grade 为 None）没有分数可比，提交即算完成。
        improves = score is None or progress.score is None or score > progress.score
        if improves:
            if score is not None:
                progress.score = score
            progress.submitted_at = timezone.now()
            progress.submission_class_id = StudentEnrollment.objects.filter(student=user, classroom__is_active=True).values_list("classroom_id", flat=True).first()
    progress.save()
    return progress
