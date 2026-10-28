"""Password mutation and one-use manual recovery; no passwords in audit."""
from datetime import timedelta
import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac, constant_time_compare
from django.views.decorators.debug import sensitive_variables

from core.api import ApiError
from .models import User, ManualPasswordReset, MaintenanceEvent
from .services import password_messages


def invalid_reset():
    return ApiError("reset_invalid", "重置凭据无效、已过期或已使用，请联系维护人员重新核实。")


def credential_digest(credential):
    return salted_hmac("huaxia.manual_password_reset", credential, algorithm="sha256").hexdigest()


@sensitive_variables()
def parse_password_payload(payload, *, reset=False):
    allowed = {"credential", "newPassword"} if reset else {"currentPassword", "newPassword"}
    if set(payload) - allowed:
        raise ApiError("invalid_fields", "包含不支持的字段。")
    errors = {}
    for key in allowed:
        value = payload.get(key)
        maximum = 128
        if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            errors[key] = ["请填写有效文字，长度不能超过128个字符。"]
    if errors:
        raise ApiError("validation_error", "请检查填写内容。", fields=errors)
    return payload


@sensitive_variables()
def check_new_password(user, password):
    if password.isspace():
        raise ApiError("validation_error", "请检查密码。", fields={"newPassword": ["密码不能全部为空白字符。"]})
    try:
        validate_password(password, user)
    except ValidationError as error:
        raise ApiError("validation_error", "请检查密码。", fields={"newPassword": password_messages(error)}) from None
    if user.check_password(password):
        raise ApiError("validation_error", "请检查密码。", fields={"newPassword": ["新密码必须与当前密码不同。"]})


def password_audit(user, action):
    MaintenanceEvent.objects.create(actor=user, action=action, target=str(user.pk), before={"username": user.username}, after={"allOldSessionsRevoked": True})


@sensitive_variables()
@transaction.atomic
def change_password(user_id, payload):
    user = User.objects.select_for_update().get(pk=user_id)
    if not user.is_active:
        raise ApiError("authentication_required", "登录已失效，请重新登录。", 401)
    if not user.check_password(payload["currentPassword"]):
        raise ApiError("current_password_invalid", "当前密码不正确。", 400)
    check_new_password(user, payload["newPassword"])
    user.set_password(payload["newPassword"])
    user.session_revision += 1
    user.save(update_fields=["password", "session_revision"])
    ManualPasswordReset.objects.filter(user=user, consumed_at__isnull=True).update(consumed_at=timezone.now())
    password_audit(user, "password_changed")


@sensitive_variables()
@transaction.atomic
def issue_manual_reset(actor_id, user_id, version, actor_password):
    from .maintenance import allowed, editable_users
    actor = User.objects.select_for_update().get(pk=actor_id)
    if not allowed(actor):
        raise ValidationError("维护权限已失效。")
    if not actor.check_password(actor_password):
        raise ValidationError("维护账号的当前密码不正确，未生成凭据。")
    user = editable_users().select_for_update().filter(pk=user_id, is_active=True).first()
    if user is None or user.pk == actor.pk:
        raise ValidationError("只能为已启用的普通账号生成重置凭据。")
    if user.session_revision != version:
        raise ValidationError("账号已变化，请重新核对当前版本。")
    credential = secrets.token_urlsafe(32)
    expires = timezone.now() + timedelta(minutes=15)
    ManualPasswordReset.objects.update_or_create(user=user, defaults={"digest": credential_digest(credential), "issued_revision": user.session_revision, "auth_stamp": user.get_session_auth_hash(), "expires_at": expires, "consumed_at": None})
    MaintenanceEvent.objects.create(actor=actor, action="password_reset_issued", target=str(user.pk), before={"username": user.username}, after={"expiresAt": expires.isoformat()})
    return credential, expires


@sensitive_variables()
@transaction.atomic
def redeem_manual_reset(payload):
    digest = credential_digest(payload["credential"])
    user_id = ManualPasswordReset.objects.filter(digest=digest).values_list("user_id", flat=True).first()
    if user_id is None:
        raise invalid_reset()
    # All writers lock User before reset row, including reissue and maintenance.
    user = User.objects.select_for_update().get(pk=user_id)
    reset = ManualPasswordReset.objects.select_for_update().filter(user=user, digest=digest).first()
    if reset is None or reset.consumed_at or reset.expires_at <= timezone.now() or reset.issued_revision != user.session_revision or not constant_time_compare(reset.auth_stamp, user.get_session_auth_hash()) or not user.is_active or user.is_staff or user.is_superuser or user.groups.filter(name="maintainer").exists():
        raise invalid_reset()
    check_new_password(user, payload["newPassword"])
    user.set_password(payload["newPassword"])
    user.session_revision += 1
    user.save(update_fields=["password", "session_revision"])
    reset.consumed_at = timezone.now()
    reset.save(update_fields=["consumed_at"])
    password_audit(user, "password_reset_completed")
