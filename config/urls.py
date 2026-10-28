from django.urls import include, path

from core.views import home, live

urlpatterns = [
    path("auth/", include("accounts.urls")),
    path("teacher/", include("classrooms.urls")),
    path("maintenance/", include("accounts.maintenance_urls")),
    path("", home, name="home"),
    path("health/live/", live, name="health-live"),
]
