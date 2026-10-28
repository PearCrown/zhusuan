"""Canonical contact policy. No account creation, merging or verification here."""
import re
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


def normalize_contact(kind, value):
    if not isinstance(value, str) or not isinstance(kind, str):
        raise ValidationError("联系方式格式无效。")
    value = value.strip()
    if kind == "email":
        # Product policy: email identities are case-insensitive; no provider aliases.
        if not value.isascii() or len(value) > 254:
            raise ValidationError("请使用有效的ASCII邮箱地址。")
        validate_email(value)
        return value.lower()
    if kind == "phone":
        # Require explicit country code; never infer it from browser locale.
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
            raise ValidationError("手机号须包含+国家码及8至15位数字。")
        return value
    raise ValidationError("不支持此联系方式类型。")
