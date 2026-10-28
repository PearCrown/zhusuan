"""Bootstrap/control an isolated Windows PostgreSQL; never installs a service."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

from dotenv import dotenv_values
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / ".local"
PG_BIN = LOCAL / "postgres" / "pgsql" / "bin"
DATA = LOCAL / "pgdata"
LOG = LOCAL / "postgres.log"
ADMIN_PASSWORD = LOCAL / "pgadmin.password"


def run_pg(program, *arguments):
    # PostgreSQL children can inherit pipe handles on Windows. Use a real
    # file rather than PIPE so a successful start cannot wait forever for EOF.
    LOCAL.mkdir(exist_ok=True)
    with (LOCAL / "bootstrap.log").open("ab") as output:
        result = subprocess.run(
            [str(PG_BIN / f"{program}.exe"), *map(str, arguments)],
            stdout=output,
            stderr=output,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    if result.returncode:
        # No connection strings or credentials are included in arguments/output.
        raise RuntimeError(f"{program} 未成功。请检查本地数据库状态与 .local/postgres.log。")


def create_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        return
    config = {
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
        "DJANGO_DEBUG": "true",
        "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
        "DB_NAME": "huaxia_accounts",
        "DB_USER": "huaxia_app",
        "DB_PASSWORD": secrets.token_urlsafe(32),
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "55432",
    }
    with env_file.open("x", encoding="utf-8") as file:
        file.write("# 本地开发配置，包含秘密，不可提交或分享。\n")
        file.writelines(f"{key}={value}\n" for key, value in config.items())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    if not (PG_BIN / "pg_ctl.exe").exists():
        raise RuntimeError("缺少本地 PostgreSQL 程序，请按 README 放置可信来源的二进制文件。")
    if args.action in {"stop", "status"}:
        run_pg("pg_ctl", "-D", DATA, args.action, *(["-m", "fast", "-w"] if args.action == "stop" else []))
        print("本地数据库操作完成。")
        return

    LOCAL.mkdir(exist_ok=True)
    create_env()
    values = dotenv_values(ROOT / ".env")
    required = ["DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT"]
    if any(not values.get(key) for key in required):
        raise RuntimeError(".env 缺少 DB_* 必要配置。")
    if values["DB_HOST"] != "127.0.0.1":
        raise RuntimeError("此脚本仅管理127.0.0.1上的独立开发数据库。外部数据库请单独管理。")
    if not values["DB_PORT"].isdigit() or not 1 <= int(values["DB_PORT"]) <= 65535:
        raise RuntimeError("DB_PORT 配置无效。")

    if not (DATA / "PG_VERSION").exists():
        if DATA.exists() and any(DATA.iterdir()):
            raise RuntimeError("数据库目录非空且未完成初始化，请核查；不会自动删除。")
        if not ADMIN_PASSWORD.exists():
            ADMIN_PASSWORD.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        run_pg(
            "initdb", "-D", DATA, "-U", "huaxia_local_admin",
            "--pwfile", ADMIN_PASSWORD, "--auth=scram-sha-256",
            "--encoding=UTF8", "--locale=C",
        )
    if not ADMIN_PASSWORD.exists():
        raise RuntimeError("本地管理员凭据缺失；不会重置或覆盖已有数据库。")
    status = subprocess.run(
        [str(PG_BIN / "pg_ctl.exe"), "-D", str(DATA), "status"],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if status.returncode:
        run_pg("pg_ctl", "-D", DATA, "-l", LOG, "-o", f"-h 127.0.0.1 -p {values['DB_PORT']}", "-w", "start")

    # The bootstrap administrator is separate from the application's DB role.
    with psycopg.connect(
        host="127.0.0.1", port=values["DB_PORT"], dbname="postgres",
        user="huaxia_local_admin", password=ADMIN_PASSWORD.read_text(encoding="utf-8"),
        connect_timeout=5, autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [values["DB_USER"]])
            if not cursor.fetchone():
                cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                    sql.Identifier(values["DB_USER"]), sql.Literal(values["DB_PASSWORD"]),
                ))
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [values["DB_NAME"]])
            if not cursor.fetchone():
                cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                    sql.Identifier(values["DB_NAME"]), sql.Identifier(values["DB_USER"]),
                ))
    with psycopg.connect(
        host=values["DB_HOST"], port=values["DB_PORT"], dbname=values["DB_NAME"],
        user=values["DB_USER"], password=values["DB_PASSWORD"], connect_timeout=5,
    ) as connection:
        connection.execute("SELECT 1")
    print("本地 PostgreSQL 已启动并验证连接；本次启动未执行应用迁移。")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except (OSError, psycopg.Error, subprocess.TimeoutExpired):
        # Avoid provider errors containing credentials or sensitive SQL.
        print("本地数据库操作失败：请核对程序路径、DB_*配置、端口及本地日志；不会自动删除数据。", file=sys.stderr)
        sys.exit(1)
