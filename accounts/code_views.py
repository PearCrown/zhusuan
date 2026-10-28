from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.decorators.debug import sensitive_variables, sensitive_post_parameters
from core.api import api_endpoint, api_methods, requires_json_body, read_json, success, ApiError
from .code_flows import issue, verify


@api_endpoint
@sensitive_variables()
@sensitive_post_parameters("code", "newPassword", "currentPassword")
@requires_json_body
@api_methods("POST")
def operation(request, purpose, stage):
    if request.GET:
        raise ApiError("invalid_query", "不接受查询参数。")
    return success((issue if stage == "request" else verify)(request, purpose, read_json(request)), status=202 if stage == "request" else 200)


@never_cache
@require_safe
def page(request):
    return render(request, "verification.html")
