from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection


class Command(BaseCommand):
    help = "Read-only PostgreSQL connectivity check; optionally assert no application tables exist."

    def add_arguments(self, parser):
        parser.add_argument("--expect-empty", action="store_true")

    def handle(self, *args, **options):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise CommandError("数据库查询未得到预期结果。")
                tables = connection.introspection.table_names(cursor)
        except DatabaseError:
            raise CommandError("PostgreSQL连接或查询失败；请检查服务和DB_*配置。未输出连接凭据。") from None
        finally:
            connection.close()
        if options["expect_empty"] and tables:
            raise CommandError("数据库已有应用表；当前阶段要求空数据库，请核查，勿直接删除。")
        self.stdout.write(self.style.SUCCESS(f"PostgreSQL连接通过；应用表数量：{len(tables)}。"))
