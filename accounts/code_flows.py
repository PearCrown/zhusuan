"""One-use purpose/browser/account-bound challenges. Never log message payloads."""
from datetime import timedelta
import secrets
import uuid
from django.conf import settings
from django.contrib.auth import login as django_login
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.crypto import salted_hmac, constant_time_compare
from django.views.decorators.debug import sensitive_variables
from core.api import ApiError
from .models import User, VerifiedContact, ContactChallenge, MaintenanceEvent, ManualPasswordReset
from .contacts import normalize_contact
from .messaging import get_sender, CodeMessage, DeliveryUnavailable
from .authentication import authenticated_user
from .passwords import check_new_password, password_audit, parse_password_payload
from .services import user_identity, end_login
from .rate_limits import consume_limit, canonical_address


def invalid():
    return ApiError("code_invalid", "验证码无效、已过期或已使用，请重新申请。", 400)


def digest(domain, value):
    return salted_hmac("huaxia.code." + domain, value, algorithm="sha256").hexdigest()


def supported():
    # No production provider has been installed. Fail identically for all addresses.
    sender = get_sender()
    if settings.CONTACT_MESSAGE_BACKEND == "disabled":
        raise ApiError("code_unavailable", "验证码服务尚未开放，请使用用户名密码或联系维护人员。", 503)
    return sender


def limit(scope, subject, window, count):
    decision = consume_limit(scope, subject, window=window, limit=count)
    if not decision.allowed:
        raise ApiError("rate_limited", "操作过于频繁，请稍后重试。", 429)


def eligible(user):
    return user.is_active and not user.is_staff and not user.is_superuser and not user.groups.filter(name="maintainer").exists()


def address(payload):
    try:
        return payload["kind"], normalize_contact(payload["kind"], payload["destination"])
    except (KeyError, ValidationError):
        raise ApiError("validation_error", "请填写有效的邮箱或含国家码的手机号。") from None


@sensitive_variables()
def issue(request, purpose, payload):
    sender = supported()
    allowed = {"kind", "destination", "currentPassword"} if purpose == "bind" else {"kind", "destination"}
    if set(payload) != allowed:
        raise ApiError("invalid_fields", "请求字段缺失或包含不支持字段。")
    kind, destination = address(payload)
    limit("code_issue_ip", canonical_address(request.META.get("REMOTE_ADDR")), 600, 30)
    limit("code_issue_address", kind + ":" + destination, 3600, 10)
    limit("code_issue_cooldown", kind + ":" + destination, 60, 1)
    actor = authenticated_user(request) if purpose == "bind" else None
    if actor:
        limit("code_bind_user", str(actor.pk), 600, 10)
    password = payload.get("currentPassword")
    if actor and (not isinstance(password, str) or not 1 <= len(password) <= 128):
        raise ApiError("validation_error", "请填写当前密码。")
    nonce = request.session.get("code_browser")
    if not nonce:
        nonce = secrets.token_urlsafe(32)
        request.session["code_browser"] = nonce
    if not request.user.is_authenticated:
        request.session.set_expiry(600)
    try:
        with transaction.atomic():
            user_id = actor.pk if actor else VerifiedContact.objects.filter(kind=kind, value=destination).values_list("user_id", flat=True).first()
            user = User.objects.select_for_update().filter(pk=user_id).first() if user_id else None
            if actor:
                if not eligible(user) or user.get_session_auth_hash() != actor.get_session_auth_hash():
                    raise ApiError("authentication_required", "登录已失效或不支持此账号操作。", 401)
                if not user.check_password(password):
                    raise ApiError("current_password_invalid", "当前密码不正确。")
                if VerifiedContact.objects.filter(user=user, kind=kind).exists():
                    raise ApiError("contact_exists", "此类联系方式已经绑定，更换功能尚未开放。", 409)
            elif user and (not eligible(user) or not VerifiedContact.objects.filter(user=user, kind=kind, value=destination).exists()):
                user = None
            challenge = ContactChallenge(user=user, purpose=purpose, kind=kind, destination=destination,
                browser_digest=digest("browser", nonce), auth_stamp=user.get_session_auth_hash() if user else "",
                expires_at=timezone.now() + timedelta(minutes=5))
            code = f"{secrets.randbelow(1000000):06d}"
            challenge.code_digest = digest("secret", f"{challenge.pk}:{purpose}:{code}")
            # Reissuing invalidates this browser's earlier challenge for this address/purpose.
            ContactChallenge.objects.filter(browser_digest=challenge.browser_digest, kind=kind, destination=destination, purpose=purpose, consumed_at__isnull=True).update(consumed_at=timezone.now())
            challenge.save()
            if user:
                sender.send(CodeMessage(kind, destination, purpose, code))
    except DeliveryUnavailable:
        raise ApiError("code_unavailable", "消息发送未确认，请稍后重新申请。", 503) from None
    return {"challengeId": str(challenge.pk), "expiresIn": 300, "message": "若此操作可用，验证码将发送到指定地址。"}


@sensitive_variables()
def verify(request, purpose, payload):
    supported()
    allowed = {"challengeId", "code", "newPassword"} if purpose == "reset" else {"challengeId", "code"}
    if set(payload) != allowed:
        raise ApiError("invalid_fields", "请求字段缺失或包含不支持字段。")
    limit("code_verify_ip", canonical_address(request.META.get("REMOTE_ADDR")), 600, 60)
    try:
        key = uuid.UUID(payload["challengeId"]) if isinstance(payload["challengeId"], str) else None
    except ValueError:
        key = None
    code = payload["code"]
    if not key or not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        raise invalid()
    if purpose == "reset":
        parse_password_payload({"credential": "code", "newPassword": payload["newPassword"]}, reset=True)
    actor = authenticated_user(request) if purpose == "bind" else None
    nonce = request.session.get("code_browser", "")
    try:
        result = _consume(request, purpose, key, code, nonce, actor, payload.get("newPassword"))
    except IntegrityError as error:
        constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", "")
        if constraint in {"contact_identity_unique", "contact_user_kind_unique"}:
            raise ApiError("contact_unavailable", "该联系方式不能绑定，请重新核实。", 409) from None
        raise
    if result is None:
        # Outside atomic: failed-attempt counter must commit, not roll back.
        raise invalid()
    if purpose != "login":
        end_login(request)
    return result


@sensitive_variables()
@transaction.atomic
def _consume(request, purpose, key, code, nonce, actor, new_password):
    snapshot = ContactChallenge.objects.filter(pk=key).values("user_id").first()
    if not snapshot or not snapshot["user_id"]:
        return None
    user = User.objects.select_for_update().get(pk=snapshot["user_id"])
    item = ContactChallenge.objects.select_for_update().get(pk=key)
    if item.purpose != purpose or not nonce or not constant_time_compare(item.browser_digest, digest("browser", nonce)):
        return None
    if item.consumed_at or item.attempts >= 5 or item.expires_at <= timezone.now() or not eligible(user) or not constant_time_compare(item.auth_stamp, user.get_session_auth_hash()):
        return None
    if actor and (actor.pk != user.pk or actor.get_session_auth_hash() != user.get_session_auth_hash()):
        return None
    if purpose != "bind" and not VerifiedContact.objects.filter(user=user, kind=item.kind, value=item.destination).exists():
        return None
    if not constant_time_compare(item.code_digest, digest("secret", f"{item.pk}:{purpose}:{code}")):
        item.attempts += 1
        item.save(update_fields=["attempts"])
        return None
    if purpose == "bind":
        VerifiedContact.objects.create(user=user, kind=item.kind, value=item.destination, verified_at=timezone.now())
        user.session_revision += 1
        user.save(update_fields=["session_revision"])
        MaintenanceEvent.objects.create(actor=user, action="contact_bound", target=str(user.pk), before={}, after={"kind": item.kind, "allOldSessionsRevoked": True})
        result = {"bound": True, "loginRequired": True}
    elif purpose == "reset":
        check_new_password(user, new_password)
        user.set_password(new_password)
        user.session_revision += 1
        user.save(update_fields=["password", "session_revision"])
        ManualPasswordReset.objects.filter(user=user, consumed_at__isnull=True).update(consumed_at=timezone.now())
        password_audit(user, "password_reset_by_code")
        result = {"passwordChanged": True, "loginRequired": True}
    else:
        identity = user_identity(user)
        request.session.flush()
        django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session.set_expiry(timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE))
        result = {"user": identity, "csrfToken": get_token(request)}
    item.consumed_at = timezone.now()
    item.save(update_fields=["consumed_at"])
    return result
