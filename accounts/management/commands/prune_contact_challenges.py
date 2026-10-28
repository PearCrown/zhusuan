from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from accounts.models import ContactChallenge


class Command(BaseCommand):
    help = "预览或分批清理过期验证码挑战，不删除账号、已验证联系方式或审计。"

    def add_arguments(self, parser):
        parser.add_argument("--retention-days", type=int, default=1)
        parser.add_argument("--batch-size", type=int, default=200)
        parser.add_argument("--max-batches", type=int, default=10)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        days, size, batches = options["retention_days"], options["batch_size"], options["max_batches"]
        if not 1 <= days <= 365 or not 1 <= size <= 1000 or not 1 <= batches <= 1000:
            raise CommandError("保留天数1—365、批量1—1000、批次数1—1000。")
        cutoff = timezone.now() - timedelta(days=days)
        candidates = ContactChallenge.objects.filter(expires_at__lt=cutoff)
        if not options["execute"]:
            self.stdout.write(f"预览：符合保留期的记录{candidates.count()}条；未删除。")
            return
        deleted = 0
        for _ in range(batches):
            with transaction.atomic():
                ids = list(candidates.select_for_update(skip_locked=True).order_by("expires_at", "pk").values_list("pk", flat=True)[:size])
                if not ids:
                    break
                count, _ = ContactChallenge.objects.filter(pk__in=ids, expires_at__lt=cutoff).delete()
                deleted += count
        self.stdout.write(f"已清理{deleted}条过期挑战；锁定中的记录及超出本轮上限的记录留待下轮。")
