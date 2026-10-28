import json
import logging
from functools import wraps

from django.db import DatabaseError
from django.http import JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure

MAX_JSON_BYTES = 8192


def api_endpoint(view):
    logger = logging.getLogger(view.__module__)

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ApiError as error:
            return failure(error.code, error.message, error.status, error.fields)
        except DatabaseError:
            logger.error("Account API database operation failed; no request data logged.")
            return failure("service_unavailable", "服务暂不可用，请稍后重试。", 503)
        except Exception as error:
            logger.error("Account API failed unexpectedly (%s); no request data logged.", type(error).__name__)
            return failure("internal_error", "操作未完成，请稍后重试。", 500)

    wrapped.is_api_endpoint = True
    return wrapped


class ApiError(Exception):
    def __init__(self, code, message, status=400, fields=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.fields = fields or {}


def success(data, status=200):
    response = JsonResponse({"ok": True, "data": data}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def failure(code, message, status=400, fields=None):
    error = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    response = JsonResponse({"ok": False, "error": error}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def method_not_allowed(allowed):
    response = failure("method_not_allowed", "不支持此请求方式。", 405)
    response["Allow"] = ", ".join(allowed)
    return response


def csrf_failure(request, reason=""):
    if request.path.startswith("/auth/"):
        return failure("csrf_failed", "请求验证失败，请刷新页面后重试。", 403)
    return django_csrf_failure(request, reason=reason)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("invalid_json_constant")


def validate_json_headers(request):
    charset = request.content_params.get("charset", "utf-8").lower()
    if request.content_type != "application/json" or charset not in {"utf-8", "utf8"}:
        raise ApiError("unsupported_media_type", "请使用UTF-8编码的JSON请求。", 415)
    length = request.META.get("CONTENT_LENGTH")
    if length:
        try:
            size = int(length)
            if size < 0:
                raise ValueError
        except ValueError:
            raise ApiError("invalid_request", "请求长度无效。") from None
        if size > MAX_JSON_BYTES:
            raise ApiError("request_too_large", "请求内容过大。", 413)


def requires_json_body(view):
    view.requires_json_body = True
    return view


def api_methods(*methods):
    def decorate(view):
        view.api_allowed_methods = methods
        return view
    return decorate


def read_json(request):
    validate_json_headers(request)
    raw = request.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ApiError("request_too_large", "请求内容过大。", 413)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ApiError("invalid_json", "请求内容不是有效的JSON对象。") from None
    if not isinstance(payload, dict):
        raise ApiError("invalid_json", "请求内容必须为JSON对象。")
    return payload
