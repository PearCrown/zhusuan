from functools import wraps

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError

from core.api import ApiError, api_endpoint


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
