from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import math
import time

from django.conf import settings
from django.db import connection
from django.utils.crypto import salted_hmac

from .models import RateLimitBucket


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int


def canonical_address(remote_address):
    # Never trust client-supplied Forwarded/X-Forwarded-For headers.
    try:
        address = ipaddress.ip_address(remote_address)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        address = str(address)
    except (ValueError, TypeError):
        address = "unknown"
    return address


def consume_limit(scope, subject, *, window, limit):
    now = time.time()
    start = math.floor(now / window) * window
    end = start + window
    key = salted_hmac("account-rate-limit", f"{scope}|{subject}|{start}", algorithm="sha256").hexdigest()
    table = connection.ops.quote_name(RateLimitBucket._meta.db_table)
    # A single PostgreSQL UPSERT serializes competing requests across workers.
    # Denied requests do not increase the counter beyond the configured limit.
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} (key, scope, attempts, expires_at) VALUES (%s, %s, 1, %s) "
            f"ON CONFLICT (key) DO UPDATE SET attempts = {table}.attempts + 1 "
            f"WHERE {table}.attempts < %s RETURNING attempts",
            [key, scope, datetime.fromtimestamp(end, tz=timezone.utc), limit],
        )
        allowed = cursor.fetchone() is not None
    return RateLimitDecision(allowed=allowed, retry_after=max(1, math.ceil(end - now)))


def registration_limit(remote_address):
    return consume_limit(
        "register", canonical_address(remote_address),
        window=settings.REGISTER_RATE_LIMIT_WINDOW_SECONDS,
        limit=settings.REGISTER_RATE_LIMIT_MAX_ATTEMPTS,
    )


def login_ip_limit(remote_address):
    return consume_limit(
        "login-ip", canonical_address(remote_address),
        window=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        limit=settings.LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS,
    )


def login_account_limit(remote_address, username):
    return consume_limit(
        "login-account-ip", f"{canonical_address(remote_address)}|{username}",
        window=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        limit=settings.LOGIN_ACCOUNT_IP_RATE_LIMIT_MAX_ATTEMPTS,
    )
