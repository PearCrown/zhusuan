from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe
from django.views.decorators.cache import never_cache


@require_safe
@never_cache
def home(request):
    from django.conf import settings
    return render(request, "home.html", {"verification_available": settings.CONTACT_MESSAGE_BACKEND != "disabled"})


@require_safe
def live(request):
    # Liveness checks only the process; DB connectivity is checked separately.
    response = JsonResponse({"status": "ok"})
    response["Cache-Control"] = "no-store"
    return response


@require_safe
@never_cache
def ready(request):
    # DB connectivity only. Migration checks run separately during release.
    from django.db import connection, DatabaseError
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                return JsonResponse({"status": "unavailable"}, status=503)
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
