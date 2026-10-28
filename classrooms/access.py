"""Every teacher data entry point must use these fresh, explicit checks."""
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q

from accounts.roles import TEACHER
from core.api import ApiError
from .models import Classroom

VIEW = "view_class_progress"
EXPORT_ROSTER = "export_class_roster"
EXPORT_SCORES = "export_class_scores"
ALLOWED_ACTIONS = {VIEW, EXPORT_ROSTER, EXPORT_SCORES}


def teacher_classes(user, *, action=VIEW):
    """No superuser/staff bypass and no cached has_perm/identity-list checks."""
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Unknown teacher permission action")
    if not get_user_model().objects.filter(pk=user.pk, is_active=True).exists():
        raise ApiError("authentication_required", "登录已失效，请重新登录。", 401)
    if not user.groups.filter(name=TEACHER).exists():
        raise ApiError("teacher_access_required", "此操作需要已分配的教师身份与权限。", 403)
    # Read the DB on every invocation: Django's per-object permission cache
    # must not turn a revocation into an apparently successful authorization.
    for codename in {VIEW, action}:
        allowed = Permission.objects.filter(
            content_type__app_label="classrooms", content_type__model="classroom", codename=codename,
        ).filter(Q(group__user=user) | Q(user=user)).exists()
        if not allowed:
            raise ApiError("teacher_access_required", "此操作需要已分配的教师身份与权限。", 403)
    return Classroom.objects.filter(is_active=True, teacher_grants__teacher_id=user.pk)


def authorized_class(user, class_id, *, action=VIEW):
    classes = teacher_classes(user, action=action)
    try:
        key = UUID(str(class_id))
    except (ValueError, TypeError, AttributeError):
        key = None
    classroom = classes.filter(pk=key).first() if key else None
    if classroom is None:
        # Unknown, inactive and someone else's class share one response.
        raise ApiError("class_not_found", "班级不存在或未获授权。", 404)
    return classroom
