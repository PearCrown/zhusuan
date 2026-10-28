from django.urls import include, path

from core.views import home, live
from accounts.password_pages import password_page

urlpatterns = [
    path("auth/", include("accounts.urls")),
    path("teacher/", include("classrooms.urls")),
    path("game/", include("gameplay.urls")),
    path("maintenance/", include("accounts.maintenance_urls")),
    path("password/change/", password_page, {"mode": "change"}),
    path("password/reset/", password_page, {"mode": "reset"}),
    path("", home, name="home"),
    path("health/live/", live, name="health-live"),
]
