"""Provision an isolated test DB/role without granting app/test CREATEDB."""

from pathlib import Path
import secrets
import sys

from dotenv import dotenv_values
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent


def main():
    app = dotenv_values(ROOT / ".env")
    if app.get("DB_HOST") != "127.0.0.1":
        raise RuntimeError("此初始化脚本仅用于项目自有的本机数据库。")
    test_path = ROOT / ".env.test"
    if not test_path.exists():
        with test_path.open("x", encoding="utf-8") as file:
            file.write(
                "# 专用测试凭据，不可提交或分享。\n"
                "TEST_DB_NAME=test_huaxia_accounts\n"
                "TEST_DB_USER=huaxia_test\n"
                f"TEST_DB_PASSWORD={secrets.token_urlsafe(32)}\n"
                "TEST_DB_HOST=127.0.0.1\n"
                f"TEST_DB_PORT={app['DB_PORT']}\n"
            )
    test = dotenv_values(test_path)
    if (
        not all(test.get(key) for key in ["TEST_DB_NAME", "TEST_DB_USER", "TEST_DB_PASSWORD", "TEST_DB_HOST", "TEST_DB_PORT"])
        or not test["TEST_DB_NAME"].startswith("test_huaxia_")
        or test["TEST_DB_NAME"] == app["DB_NAME"]
        or test["TEST_DB_USER"] == app["DB_USER"]
        or test["TEST_DB_HOST"] != "127.0.0.1"
        or test["TEST_DB_PORT"] != app["DB_PORT"]
    ):
        raise RuntimeError("测试数据库配置未满足隔离条件。")
    with psycopg.connect(
        host="127.0.0.1", port=app["DB_PORT"], dbname="postgres",
        user="huaxia_local_admin", connect_timeout=5, autocommit=True,
        password=(ROOT / ".local" / "pgadmin.password").read_text(encoding="utf-8"),
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=%s", [test["TEST_DB_USER"]])
            existing = cursor.fetchone()
            if existing and any(existing):
                raise RuntimeError("现有测试角色权限过高，拒绝继续。")
            if existing is None:
                cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                    sql.Identifier(test["TEST_DB_USER"]), sql.Literal(test["TEST_DB_PASSWORD"]),
                ))
            cursor.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", [test["TEST_DB_NAME"]])
            existing_db = cursor.fetchone()
            if existing_db and existing_db[0] != test["TEST_DB_USER"]:
                raise RuntimeError("现有测试数据库不属于预期账号，拒绝继续。")
            if existing_db is None:
                cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                    sql.Identifier(test["TEST_DB_NAME"]), sql.Identifier(test["TEST_DB_USER"]),
                ))
            # Prevent either ordinary role from connecting to the other DB.
            for dbname, owner in [(app["DB_NAME"], app["DB_USER"]), (test["TEST_DB_NAME"], test["TEST_DB_USER"])]:
                cursor.execute(sql.SQL("REVOKE CONNECT, TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname)))
                cursor.execute(sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(sql.Identifier(dbname), sql.Identifier(owner)))
            cursor.execute("SELECT has_database_privilege(%s, %s, 'CONNECT')", [test["TEST_DB_USER"], app["DB_NAME"]])
            if cursor.fetchone()[0]:
                raise RuntimeError("测试角色仍可连接开发库，拒绝继续。")
            cursor.execute("SELECT has_database_privilege(%s, %s, 'CONNECT')", [app["DB_USER"], test["TEST_DB_NAME"]])
            if cursor.fetchone()[0]:
                raise RuntimeError("开发角色仍可连接测试库，拒绝继续。")
    with psycopg.connect(
        host=test["TEST_DB_HOST"], port=test["TEST_DB_PORT"], dbname=test["TEST_DB_NAME"],
        user=test["TEST_DB_USER"], password=test["TEST_DB_PASSWORD"], connect_timeout=5,
    ) as connection:
        connection.execute("SELECT 1")
    print("独立测试数据库已就绪；测试与开发角色互不具备对方数据库连接权限。")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except (KeyError, OSError, psycopg.Error):
        print("测试环境准备失败，请检查本机数据库、配置和独立角色；未输出凭据。", file=sys.stderr)
        sys.exit(1)
