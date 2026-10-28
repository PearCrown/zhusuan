from django.urls import path
from . import views

urlpatterns = [
    path("", views.workspace),
    path("api/chapters", views.chapters),
    path("api/chapters/<str:chapter_id>/progress", views.progress),
    path("api/chapters/<str:chapter_id>/action", views.action),
    path("api/teacher/classes/<str:class_id>/scores", views.teacher_scores),
    path("api/teacher/classes/<str:class_id>/scores.csv", views.teacher_scores_csv),
]
