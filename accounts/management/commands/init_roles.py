from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.roles import ROLE_PERMISSIONS


class Command(BaseCommand):
    help = "幂等初始化项目专用角色及其权限，不创建用户，不修改班级授权。"

    @transaction.atomic
    def handle(self, *args, **options):
        for name, definitions in ROLE_PERMISSIONS.items():
            permissions = []
            for app, model, codename in definitions:
                try:
                    permission = Permission.objects.get(
                        content_type__app_label=app,
                        content_type__model=model,
                        codename=codename,
                    )
                except Permission.DoesNotExist:
                    raise CommandError("权限尚未生成，请先完成数据库迁移。") from None
                permissions.append(permission)
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(permissions)
        self.stdout.write(self.style.SUCCESS("项目角色已初始化；未创建用户或授予管理后台访问权限。"))
