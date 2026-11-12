from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme

from core.api import ApiError, api_endpoint


def _safe_next(raw):
    """只允许站内相对路径作为跳转目标，防止开放重定向。"""
    if not raw or not isinstance(raw, str):
        return ""
    if not raw.startswith("/") or raw.startswith("//"):
        return ""
    if not url_has_allowed_host_and_scheme(raw, allowed_hosts=None, require_https=False):
        return ""
    return raw


def login_required_page(view):
    """未登录访问受保护页面 → 302 跳回登录页，并带上 next 参数。"""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and user.is_active):
            target = _safe_next(request.get_full_path())
            query = f"?{urlencode({'next': target})}" if target else ""
            return HttpResponseRedirect(f"/{query}")
        return view(request, *args, **kwargs)
    return wrapped


def authenticated_user(request):
    try:
        user = request.user
        valid = user.is_authenticated and user.is_active
    except (ValidationError, ValueError, TypeError):
        valid = False
    if not valid:
        # This also invalidates sessions for disabled accounts instead of
        # allowing the same token to revive when the account is re-enabled.
        if request.session.session_key:
            request.session.flush()
        request.user = AnonymousUser()
        raise ApiError("authentication_required", "登录已失效，请重新登录。", 401)
    return user


def login_required_api(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        request.account_user = authenticated_user(request)
        return view(request, *args, **kwargs)
    # Make the reusable guard safe on its own; callers need not remember a
    # second decorator or a particular wrapping order to get JSON failures.
    return api_endpoint(wrapped)
