from django.urls import path

from . import views, code_views

urlpatterns = [
    path("csrf", views.csrf, name="auth-csrf"),
    path("register", views.register, name="auth-register"),
    path("login", views.login, name="auth-login"),
    path("me", views.me, name="auth-me"),
    path("logout", views.logout, name="auth-logout"),
    path("password/change", views.password_change, name="auth-password-change"),
    path("password/reset", views.password_reset, name="auth-password-reset"),
]

for purpose in ("bind", "login", "reset"):
    for stage in ("request", "verify"):
        urlpatterns.append(path(f"code/{purpose}/{stage}", code_views.operation, {"purpose": purpose, "stage": stage}))
