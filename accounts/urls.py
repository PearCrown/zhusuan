from django.urls import path

from . import views

urlpatterns = [
    path("csrf", views.csrf, name="auth-csrf"),
    path("register", views.register, name="auth-register"),
    path("login", views.login, name="auth-login"),
    path("me", views.me, name="auth-me"),
    path("logout", views.logout, name="auth-logout"),
]
