from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from accounts.models import User, MaintenanceEvent
from accounts.maintenance import allowed
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError


class Command(BaseCommand):
    help = "由可信本机终端为已有账号授予/撤销受限维护身份；不创建账号或设置密码。"

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--revoke", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [74280317])
        try:
            user = User.objects.select_for_update().get(username=User.normalize_username(options["username"]))
            group = Group.objects.get(name="maintainer")
        except (User.DoesNotExist, Group.DoesNotExist, ValidationError):
            raise CommandError("账号或角色不存在，请先注册账号并执行init_roles。") from None
        if not user.is_active or not user.has_usable_password() or user.is_staff or user.is_superuser:
            raise CommandError("请选择已启用、可用密码登录的普通账号。")
        before = user.groups.filter(name="maintainer").exists()
        if options["revoke"]:
            if before and not User.objects.filter(is_active=True, groups=group).exclude(pk=user.pk).exists():
                raise CommandError("不能撤销最后一个启用的维护账号，请先准备另一名维护人员。")
            user.groups.remove(group)
        else:
            user.groups.add(group)
            if not allowed(user):
                raise CommandError("维护权限未初始化完整，请先执行init_roles。")
        user.session_revision += 1
        user.save(update_fields=["session_revision"])
        MaintenanceEvent.objects.create(actor=user, action="bootstrap_maintainer", target=str(user.pk), before={"maintainer": before}, after={"maintainer": not options["revoke"]})
        self.stdout.write("维护身份已更新并记录；此账号所有旧会话已撤销，请重新登录。")
