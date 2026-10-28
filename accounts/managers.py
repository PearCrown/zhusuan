from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.exceptions import ValidationError

from .validators import normalize_display_name, normalize_username


class UserManager(DjangoUserManager):
    def _create_user_object(self, username, email, password, **extra_fields):
        username = normalize_username(username)
        # Only omission gets the internal default; explicit invalid input must
        # fail instead of silently becoming a different value.
        extra_fields["display_name"] = normalize_display_name(extra_fields.get("display_name", username))
        return super()._create_user_object(username, email, password, **extra_fields)

    def create_user(self, username, email=None, password=None, **extra_fields):
        if extra_fields.get("is_staff") or extra_fields.get("is_superuser"):
            raise ValueError("普通用户创建入口不能授予维护权限。")
        return super().create_user(username, email, password, **extra_fields)

    create_user.alters_data = True

    async def acreate_user(self, username, email=None, password=None, **extra_fields):
        if extra_fields.get("is_staff") or extra_fields.get("is_superuser"):
            raise ValueError("普通用户创建入口不能授予维护权限。")
        return await super().acreate_user(username, email, password, **extra_fields)

    acreate_user.alters_data = True

    def get_by_natural_key(self, username):
        try:
            username = normalize_username(username)
        except ValidationError:
            raise self.model.DoesNotExist from None
        return super().get_by_natural_key(username)

    async def aget_by_natural_key(self, username):
        try:
            username = normalize_username(username)
        except ValidationError:
            raise self.model.DoesNotExist from None
        return await super().aget_by_natural_key(username)
