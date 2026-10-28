from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables
from django.middleware.csrf import rotate_token
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from core.api import ApiError
from classrooms.models import StudentEnrollment, TeacherClassGrant
from .roles import ROLE_PERMISSIONS, STUDENT, TEACHER
from .validators import normalize_display_name, normalize_username


def password_messages(error):
    messages = []
    for item in error.error_list:
        code = item.code
        if code == "password_too_short":
            messages.append(f"密码至少需要{item.params['min_length']}个字符。")
        elif code == "password_too_similar":
            messages.append("密码不能与用户名或显示名称过于相似。")
        elif code == "password_too_common":
            messages.append("密码过于常见，请更换。")
        elif code == "password_entirely_numeric":
            messages.append("密码不能全部为数字。")
        else:
            messages.append("密码不符合强度要求，请更换。")
    return messages


@sensitive_variables()
def registration_input(payload):
    allowed = {"username", "displayName", "password"}
    if set(payload) - allowed:
        raise ApiError("invalid_fields", "包含不支持的字段。")
    errors = {}
    normalized = {}
    for key, normalizer in [("username", normalize_username), ("displayName", normalize_display_name)]:
        if key not in payload:
            errors[key] = ["请填写此字段。"]
            continue
        try:
            normalized[key] = normalizer(payload[key])
        except ValidationError as error:
            errors[key] = error.messages
    password = payload.get("password")
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        errors["password"] = ["密码必须为1至128个字符的文字，且须满足密码强度要求。"]
    elif password.isspace():
        errors["password"] = ["密码不能全部为空白字符。"]
    elif any(0xD800 <= ord(char) <= 0xDFFF for char in password):
        errors["password"] = ["密码包含无效的文字编码，请重新输入。"]
    if errors:
        raise ApiError("validation_error", "请检查填写内容。", fields=errors)
    user = get_user_model()(username=normalized["username"], display_name=normalized["displayName"])
    try:
        validate_password(password, user=user)
    except ValidationError as error:
        raise ApiError("validation_error", "请检查密码。", fields={"password": password_messages(error)}) from None
    return user, password


def assign_student_role(user, group):
    user.groups.add(group)


@sensitive_variables()
def register_student(payload):
    user, password = registration_input(payload)
    # Hash outside the write transaction so expensive computation holds no locks.
    user.set_password(password)
    try:
        with transaction.atomic():
            try:
                group = Group.objects.get(name=STUDENT)
            except Group.DoesNotExist:
                raise ApiError("registration_unavailable", "注册暂不可用，请稍后重试。", 503) from None
            if group.permissions.exists():
                raise ApiError("registration_unavailable", "注册暂不可用，请稍后重试。", 503)
            user.save(force_insert=True)
            assign_student_role(user, group)
    except IntegrityError as error:
        constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        if constraint == "accounts_user_username_key":
            raise ApiError("username_taken", "用户名已被使用，请更换。", 409) from None
        raise
    return user


@dataclass(frozen=True)
class LoginCredentials:
    username: str
    password: str = field(repr=False)


@sensitive_variables()
def login_input(payload):
    if set(payload) - {"username", "password"}:
        raise ApiError("invalid_fields", "包含不支持的字段。")
    errors = {}
    try:
        username = normalize_username(payload.get("username"))
    except ValidationError as error:
        errors["username"] = error.messages
    password = payload.get("password")
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        errors["password"] = ["请填写有效密码，长度不能超过128个字符。"]
    elif any(0xD800 <= ord(char) <= 0xDFFF for char in password):
        errors["password"] = ["密码包含无效的文字编码，请重新输入。"]
    if errors:
        raise ApiError("validation_error", "请检查填写内容。", fields=errors)
    # Login deliberately does not re-apply registration strength rules.
    return LoginCredentials(username=username, password=password)


def user_identity(user):
    roles = list(user.groups.filter(name__in=ROLE_PERMISSIONS).order_by("name").values_list("name", flat=True))
    class_id = StudentEnrollment.objects.filter(student_id=user.pk, classroom__is_active=True).values_list("classroom_id", flat=True).first()
    teaching_classes = []
    if TEACHER in roles:
        teaching_classes = list(TeacherClassGrant.objects.filter(
            teacher_id=user.pk, classroom__is_active=True,
        ).order_by("classroom_id").values_list("classroom_id", flat=True))
    return {
        "userId": str(user.pk), "username": user.username, "displayName": user.display_name,
        "roles": roles, "classId": str(class_id) if class_id else None,
        "teachingClassIds": [str(value) for value in teaching_classes],
    }


@sensitive_variables()
def start_login(request, credentials):
    user = authenticate(request, username=credentials.username, password=credentials.password)
    if user is None:
        raise ApiError("invalid_credentials", "账号或密码错误。", 401)
    with transaction.atomic():
        try:
            current = get_user_model().objects.select_for_update().get(pk=user.pk)
        except get_user_model().DoesNotExist:
            raise ApiError("invalid_credentials", "账号或密码错误。", 401) from None
        if not current.is_active or not constant_time_compare(current.password, user.password):
            raise ApiError("invalid_credentials", "账号或密码错误。", 401)
        identity = user_identity(current)
        # Fresh authentication always replaces the current browser session,
        # including re-login as the same account; cloud data is not in session.
        request.session.flush()
        django_login(request, current, backend=user.backend)
        request.session.set_expiry(timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE))
    return identity


def end_login(request):
    from django.contrib.auth.models import AnonymousUser

    with transaction.atomic():
        try:
            # Evaluate lazy identity before logout signals; malformed stored
            # identity must not turn logout into a server error.
            _ = request.user.is_authenticated
        except (ValidationError, ValueError, TypeError):
            request.user = AnonymousUser()
        django_logout(request)
    rotate_token(request)
