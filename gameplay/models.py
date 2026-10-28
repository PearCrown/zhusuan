from django.conf import settings
from django.db import models


class ChapterProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    chapter_id = models.CharField(max_length=64)
    schema_version = models.PositiveIntegerField(default=1)
    question_bank_id = models.CharField(max_length=64, default="")
    question_bank_version = models.CharField(max_length=32, default="")
    revision = models.PositiveBigIntegerField(default=0)
    state = models.JSONField(default=dict)
    score = models.PositiveIntegerField(null=True)
    submitted_at = models.DateTimeField(null=True)
    submission_class = models.ForeignKey("classrooms.Classroom", null=True, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "chapter_id"], name="one_progress_per_user_chapter"),
            models.CheckConstraint(condition=models.Q(score__isnull=True) | models.Q(score__isnull=False, score__gte=0, score__lte=100, submitted_at__isnull=False), name="chapter_result_consistent"),
        ]
