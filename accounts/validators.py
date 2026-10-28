import re
import unicodedata

from django.core.exceptions import ValidationError

from core.validators import normalize_visible_text

USERNAME_PATTERN = r"[a-z0-9][a-z0-9_.-]{2,31}"


def normalize_username(value):
    if not isinstance(value, str):
        raise ValidationError("用户名必须是文字。", code="invalid_username")
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    if re.fullmatch(USERNAME_PATTERN, value, flags=re.ASCII) is None:
        raise ValidationError(
            "用户名须为3至32位英文字母、数字、下划线、点或短横线，并以字母或数字开头。",
            code="invalid_username",
        )
    return value


def normalize_display_name(value):
    return normalize_visible_text(value, label="显示名称", max_length=60)
