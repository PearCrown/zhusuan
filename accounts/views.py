from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from core.api import ApiError, api_endpoint, api_methods, failure, method_not_allowed, read_json, requires_json_body, success
from .authentication import login_required_api
from .rate_limits import login_account_limit, login_ip_limit, registration_limit
from .services import end_login, login_input, register_student, start_login, user_identity


@api_endpoint
@ensure_csrf_cookie
@api_methods("GET", "HEAD")
def csrf(request):
    if request.method not in {"GET", "HEAD"}:
        return method_not_allowed(["GET", "HEAD"])
    return success({"csrfToken": get_token(request)})


@api_endpoint
@sensitive_post_parameters("password")
@sensitive_variables()
@requires_json_body
@api_methods("POST")
def register(request):
    if request.method != "POST":
        return method_not_allowed(["POST"])
    blocked = limited_response(registration_limit(request.META.get("REMOTE_ADDR")))
    if blocked is not None:
        return blocked
    user = register_student(read_json(request))
    return success({"userId": str(user.pk), "username": user.username, "displayName": user.display_name, "role": "student"}, status=201)


def limited_response(decision):
    if decision.allowed:
        return None
    response = failure("rate_limited", "操作过于频繁，请稍后重试。", 429)
    response["Retry-After"] = str(decision.retry_after)
    return response


@api_endpoint
@sensitive_post_parameters("password")
@sensitive_variables()
@requires_json_body
@api_methods("POST")
def login(request):
    if request.method != "POST":
        return method_not_allowed(["POST"])
    blocked = limited_response(login_ip_limit(request.META.get("REMOTE_ADDR")))
    if blocked is not None:
        return blocked
    credentials = login_input(read_json(request))
    blocked = limited_response(login_account_limit(request.META.get("REMOTE_ADDR"), credentials.username))
    if blocked is not None:
        return blocked
    identity = start_login(request, credentials)
    return success({"user": identity, "csrfToken": get_token(request)})


@login_required_api
@api_methods("GET", "HEAD")
def me(request):
    if request.method not in {"GET", "HEAD"}:
        return method_not_allowed(["GET", "HEAD"])
    return success(user_identity(request.account_user))


@api_endpoint
@requires_json_body
@api_methods("POST")
def logout(request):
    if request.method != "POST":
        return method_not_allowed(["POST"])
    if read_json(request):
        raise ApiError("invalid_fields", "退出请求不接受额外字段。")
    end_login(request)
    return success({"loggedOut": True, "csrfToken": get_token(request)})


@login_required_api
@sensitive_post_parameters("currentPassword", "newPassword")
@sensitive_variables()
@requires_json_body
@api_methods("POST")
def password_change(request):
    from .passwords import parse_password_payload, change_password
    from .rate_limits import consume_limit, canonical_address
    for scope, subject, limit in [("password_change_ip", canonical_address(request.META.get("REMOTE_ADDR")), 120), ("password_change_user", str(request.account_user.pk), 10)]:
        blocked = limited_response(consume_limit(scope, subject, window=600, limit=limit))
        if blocked is not None:
            return blocked
    change_password(request.account_user.pk, parse_password_payload(read_json(request)))
    end_login(request)
    return success({"passwordChanged": True, "loginRequired": True, "csrfToken": get_token(request)})


@api_endpoint
@sensitive_post_parameters("credential", "newPassword")
@sensitive_variables()
@requires_json_body
@api_methods("POST")
def password_reset(request):
    from .passwords import parse_password_payload, redeem_manual_reset
    from .rate_limits import consume_limit, canonical_address
    blocked = limited_response(consume_limit("password_reset_ip", canonical_address(request.META.get("REMOTE_ADDR")), window=600, limit=60))
    if blocked is not None:
        return blocked
    redeem_manual_reset(parse_password_payload(read_json(request), reset=True))
    # Also clear any other account currently signed in on this browser.
    end_login(request)
    return success({"passwordChanged": True, "loginRequired": True, "csrfToken": get_token(request)})
