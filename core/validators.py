import unicodedata

from django.core.exceptions import ValidationError


def normalize_visible_text(value, *, label, max_length):
    if not isinstance(value, str):
        raise ValidationError(f"{label}必须是文字。", code="invalid_text")
    value = value.strip()
    if not 1 <= len(value) <= max_length or any(unicodedata.category(char).startswith("C") for char in value):
        raise ValidationError(
            f"{label}须为1至{max_length}个可见字符，不能包含控制字符。", code="invalid_text",
        )
    return value
