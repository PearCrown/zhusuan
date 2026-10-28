import os
import sys


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        if "--settings=config.test_settings" not in sys.argv and os.environ.get("DJANGO_SETTINGS_MODULE") != "config.test_settings":
            sys.exit("测试必须使用隔离配置：请运行 scripts/test.ps1，避免连接开发数据库。")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
