from django.core.management.base import BaseCommand
from core.db_archive import backup


class Command(BaseCommand):
    help="将当前配置数据库备份为敏感的PostgreSQL自定义归档，不覆盖已有文件。"
    def add_arguments(self,parser):
        parser.add_argument("--output",required=True)
        parser.add_argument("--pg-bin")
    def handle(self,*args,**options):
        backup(options["output"],options["pg_bin"])
        self.stdout.write("数据库备份及完整性清单已生成；包含敏感数据，请勿上传GitHub。")
