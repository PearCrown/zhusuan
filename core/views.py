from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe
from django.views.decorators.cache import never_cache


@require_safe
@never_cache
def home(request):
    return render(request, "home.html")


@require_safe
def live(request):
    # Liveness checks only the process; DB connectivity is checked separately.
    response = JsonResponse({"status": "ok"})
    response["Cache-Control"] = "no-store"
    return response
