from django.core.management.base import BaseCommand
from core.db_archive import restore


class Command(BaseCommand):
    help="仅恢复可信归档到同服务器上的独立空数据库；不删除或覆盖原数据库。"
    def add_arguments(self,parser):
        parser.add_argument("--source",required=True)
        parser.add_argument("--target-database",required=True)
        parser.add_argument("--target-user",required=True)
        parser.add_argument("--target-password-env",required=True)
        parser.add_argument("--confirm-target",required=True)
        parser.add_argument("--pg-bin")
    def handle(self,*args,**options):
        restore(options["source"],options["target_database"],options["target_user"],options["target_password_env"],options["confirm_target"],options["pg_bin"])
        self.stdout.write("已恢复到独立目标；请使用目标配置核对迁移、数据和业务，再决定是否切换服务。")
