from django.urls import path

from . import views

urlpatterns = [
    path("", views.workspace, name="teacher-workspace"),
    path("api/classes", views.classes, name="teacher-classes"),
    path("api/classes/<str:class_id>/students", views.students, name="teacher-students"),
    path("api/classes/<str:class_id>/students.csv", views.roster_csv, name="teacher-roster-csv"),
]
