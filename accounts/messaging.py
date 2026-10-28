"""Disabled by default. Memory delivery is explicit, bounded and development-only."""
from dataclasses import dataclass, field
from collections import deque
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from .contacts import normalize_contact


class DeliveryUnavailable(Exception):
    def __init__(self):
        super().__init__("消息发送暂不可用。")


@dataclass(frozen=True)
class CodeMessage:
    kind: str
    destination: str = field(repr=False)
    purpose: str
    code: str = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, "destination", normalize_contact(self.kind, self.destination))
        if self.purpose not in ("bind", "login", "reset"):
            raise ValidationError("不支持此消息用途。")
        if not isinstance(self.code, str) or len(self.code) != 6 or not self.code.isascii() or not self.code.isdigit():
            raise ValidationError("验证码格式无效。")


class DisabledSender:
    def send(self, message):
        raise DeliveryUnavailable()


class MemorySender:
    def __init__(self):
        self._messages = deque(maxlen=100)

    def _guard(self):
        if not settings.DEBUG or settings.CONTACT_MESSAGE_BACKEND != "memory":
            self.clear()
            raise ImproperlyConfigured("内存消息发送器仅允许显式开启的开发环境。")

    def send(self, message):
        self._guard()
        if not isinstance(message, CodeMessage):
            raise ValidationError("消息格式无效。")
        self._messages.append(message)

    def drain(self):
        self._guard()
        messages = tuple(self._messages)
        self.clear()
        return messages

    def clear(self):
        self._messages.clear()


# No console/file logger, external SDK, public outbox or persistent code storage.
_memory_sender = MemorySender()
_disabled_sender = DisabledSender()


def get_sender():
    backend = settings.CONTACT_MESSAGE_BACKEND
    if backend == "disabled":
        _memory_sender.clear()
        return _disabled_sender
    if backend == "memory":
        _memory_sender._guard()
        return _memory_sender
    raise ImproperlyConfigured("不支持的消息发送器配置。")
