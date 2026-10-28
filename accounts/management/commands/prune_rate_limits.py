from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import RateLimitBucket


class Command(BaseCommand):
    help = "仅清理已过期超过24小时的限流记录，不影响活跃计数。"

    def handle(self, *args, **options):
        deleted, _ = RateLimitBucket.objects.filter(expires_at__lt=timezone.now() - timedelta(days=1)).delete()
        self.stdout.write(self.style.SUCCESS(f"已清理{deleted}条过期限流记录。"))
