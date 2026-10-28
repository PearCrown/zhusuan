import logging

from django.conf import settings
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import DatabaseError
from django.utils.cache import patch_vary_headers
from django.utils.deprecation import MiddlewareMixin

from .api import ApiError, failure, method_not_allowed, validate_json_headers

logger = logging.getLogger(__name__)


class ApiSessionMiddleware(SessionMiddleware):
    """Reuse Django sessions while keeping post-view API failures safe."""

    def process_response(self, request, response):
        try:
            return super().process_response(request, response)
        except (DatabaseError, SessionInterrupted) as error:
            match = getattr(request, "resolver_match", None)
            if not request.path.startswith(("/auth/", "/maintenance/")) and not getattr(getattr(match, "func", None), "is_api_endpoint", False):
                raise
            if isinstance(error, SessionInterrupted):
                result = failure("authentication_required", "登录已失效，请重新登录。", 401)
                result.delete_cookie(
                    settings.SESSION_COOKIE_NAME, path=settings.SESSION_COOKIE_PATH,
                    domain=settings.SESSION_COOKIE_DOMAIN, samesite=settings.SESSION_COOKIE_SAMESITE,
                )
            else:
                logger.error("Account API session persistence failed; no request data logged.")
                result = failure("service_unavailable", "服务暂不可用，请稍后重试。", 503)
            patch_vary_headers(result, ("Cookie",))
            return result


class JsonRequestGuardMiddleware(MiddlewareMixin):
    """Reject incompatible bodies before CSRF can parse POST form data."""

    def process_view(self, request, view_func, view_args, view_kwargs):
        allowed = getattr(view_func, "api_allowed_methods", None)
        if allowed and request.method not in allowed:
            return method_not_allowed(allowed)
        if not getattr(view_func, "requires_json_body", False):
            return None
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        try:
            validate_json_headers(request)
        except ApiError as error:
            return failure(error.code, error.message, error.status, error.fields)
        return None
