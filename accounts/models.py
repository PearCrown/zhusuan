import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager
from .validators import normalize_display_name, normalize_username


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField("用户名", max_length=32, unique=True)
    display_name = models.CharField("显示名称", max_length=60)
    session_revision = models.PositiveBigIntegerField(default=0, editable=False)
    # Inherited email remains optional/unverified; never use it to log in/reset
    # until the verified-contact workflow has been implemented.
    objects = UserManager()
    REQUIRED_FIELDS = ["display_name"]

    class Meta(AbstractUser.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(username__regex=r"^[a-z0-9][a-z0-9_.-]{2,31}$"),
                name="accounts_username_canonical",
            ),
            models.CheckConstraint(
                condition=~models.Q(display_name=""),
                name="accounts_display_name_not_empty",
            ),
        ]
        permissions = [("maintain_accounts", "维护账号与角色")]

    @classmethod
    def normalize_username(cls, username):
        return normalize_username(username)

    def clean(self):
        super().clean()
        self.username = normalize_username(self.username)
        self.display_name = normalize_display_name(self.display_name)

    def save(self, *args, **kwargs):
        self.username = normalize_username(self.username)
        self.display_name = normalize_display_name(self.display_name)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name

    def _get_session_auth_hash(self, secret=None):
        from django.utils.crypto import salted_hmac
        original = super()._get_session_auth_hash(secret)
        if self.session_revision == 0:
            return original
        return salted_hmac("huaxia.session_revision", f"{original}:{self.session_revision}", secret=secret, algorithm="sha256").hexdigest()


class MaintenanceEvent(models.Model):
    actor = models.ForeignKey("User", on_delete=models.PROTECT)
    action = models.CharField(max_length=32)
    target = models.CharField(max_length=64)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class RateLimitBucket(models.Model):
    key = models.CharField(primary_key=True, max_length=64)
    scope = models.CharField(max_length=32)
    attempts = models.PositiveIntegerField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(attempts__gte=1), name="rate_limit_attempts_positive"),
        ]


class ManualPasswordReset(models.Model):
    user = models.OneToOneField("User", on_delete=models.PROTECT)
    digest = models.CharField(max_length=64, unique=True)
    issued_revision = models.PositiveBigIntegerField()
    auth_stamp = models.CharField(max_length=64, default="")
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
