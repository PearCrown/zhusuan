from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from .authentication import authenticated_user
from .maintenance import safe_maintenance
from core.api import ApiError


@never_cache
@safe_maintenance
@require_safe
def password_page(request, mode):
    if mode == "change":
        try:
            authenticated_user(request)
        except ApiError:
            return HttpResponse('请先在<a href="/">账号中心登录</a>。', status=403)
    return render(request, "password.html", {"mode": mode})
