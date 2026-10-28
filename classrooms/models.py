import uuid

from django.conf import settings
from django.db import models

from core.validators import normalize_visible_text


class Classroom(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField("班级编号", max_length=32, unique=True)
    name = models.CharField("班级名称", max_length=80)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = [
            ("view_class_progress", "查看授权班级进度与成绩"),
            ("export_class_scores", "导出授权班级成绩"),
            ("export_class_roster", "导出授权班级学生名单"),
            ("maintain_class_assignments", "维护班级归属与教师授权"),
        ]
        constraints = [
            models.CheckConstraint(condition=~models.Q(code=""), name="classroom_code_not_empty"),
            models.CheckConstraint(condition=~models.Q(name=""), name="classroom_name_not_empty"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.code = normalize_visible_text(self.code, label="班级编号", max_length=32)
        self.name = normalize_visible_text(self.name, label="班级名称", max_length=80)

    def save(self, *args, **kwargs):
        self.code = normalize_visible_text(self.code, label="班级编号", max_length=32)
        self.name = normalize_visible_text(self.name, label="班级名称", max_length=80)
        return super().save(*args, **kwargs)


class StudentEnrollment(models.Model):
    student = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="enrollment",
    )
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="enrollments")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class TeacherClassGrant(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="class_grants",
    )
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="teacher_grants")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["teacher", "classroom"], name="unique_teacher_class_grant"),
        ]
