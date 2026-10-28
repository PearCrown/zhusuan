"""Trusted operator tools: custom-format PostgreSQL archives, never public APIs."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone
import psycopg
from django.conf import settings
from django.core.management.base import CommandError


def binary(name, directory=None):
    if directory:
        result = Path(directory) / (name + (".exe" if os.name == "nt" else ""))
    else:
        found = shutil.which(name)
        local = settings.BASE_DIR / ".local/postgres/pgsql/bin" / (name + ".exe")
        result = Path(found) if found else local
    if not result.is_file():
        raise CommandError("找不到PostgreSQL备份工具，请配置可信程序目录。")
    return str(result)


def pg_environment(db, *, database=None, user=None, password=None):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("PG"):
            env.pop(key)
    env.update(PGHOST=str(db["HOST"]), PGPORT=str(db["PORT"]), PGDATABASE=str(database or db["NAME"]),
        PGUSER=str(user or db["USER"]), PGPASSWORD=str(db["PASSWORD"] if password is None else password), PGCONNECT_TIMEOUT="5")
    for key in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
        if key in db.get("OPTIONS", {}):
            env["PG" + key.upper()] = str(db["OPTIONS"][key])
    return env


def checksum(stream):
    digest=hashlib.sha256()
    while block := stream.read(1024 * 1024):
        digest.update(block)
    return digest.hexdigest()


def run_tool(args, **kwargs):
    try:
        result=subprocess.run(args, stderr=subprocess.PIPE, timeout=600, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        raise CommandError("备份工具未完成；未输出数据库凭据或内部错误。") from None
    if result.returncode:
        raise CommandError("备份工具返回失败；请由维护人员检查版本、连接和权限，未输出内部错误。")


def backup(output, pg_bin=None):
    path=Path(output).resolve()
    if path.suffix != ".dump":
        raise CommandError("备份文件必须以.dump结尾。")
    manifest=Path(str(path)+".manifest.json")
    if path.exists() or manifest.exists():
        raise CommandError("备份路径已存在，拒绝覆盖。")
    tool=binary("pg_dump",pg_bin)
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    owned=False
    manifest_owned=False
    try:
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),"wb") as stream:
            owned=True
            run_tool([tool,"--format=custom","--no-owner","--no-acl","--no-password"],env=pg_environment(settings.DATABASES["default"]),stdout=stream)
        with path.open("rb") as stream:
            sha=checksum(stream)
        with os.fdopen(os.open(manifest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),"w",encoding="utf-8") as stream:
            manifest_owned=True
            json.dump({"format":1,"sha256":sha,"bytes":path.stat().st_size,"createdAt":datetime.now(timezone.utc).isoformat()},stream)
    except Exception:
        if owned:
            path.unlink(missing_ok=True)
        if manifest_owned:
            manifest.unlink(missing_ok=True)
        raise
    return path


def restore(source, target, target_user, password_env, confirm, pg_bin=None):
    db=settings.DATABASES["default"]
    if not isinstance(target,str) or not isinstance(target_user,str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}",target) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}",target_user) or target == db["NAME"] or confirm != target or not target_user or target_user == db["USER"]:
        raise CommandError("恢复必须指定不同的空数据库、独立普通账号及完全匹配的confirm-target。")
    password=os.environ.get(password_env, "")
    if not password:
        raise CommandError("未提供目标数据库密码环境变量。")
    path=Path(source).resolve()
    tool=binary("pg_restore",pg_bin)
    try:
        manifest=json.loads(Path(str(path)+".manifest.json").read_text(encoding="utf-8"))
        stream=path.open("rb")
    except (OSError, ValueError):
        raise CommandError("无法读取备份或完整性清单。") from None
    with stream:
        if not isinstance(manifest,dict) or manifest.get("format") != 1 or manifest.get("bytes") != path.stat().st_size or manifest.get("sha256") != checksum(stream):
            raise CommandError("备份完整性校验失败，未连接恢复目标。")
        stream.seek(0)
        connection_args={"host":db["HOST"],"port":db["PORT"],"dbname":target,"user":target_user,"password":password,"connect_timeout":5}
        connection_args.update({k:v for k,v in db.get("OPTIONS",{}).items() if k in {"sslmode","sslrootcert","sslcert","sslkey"}})
        try:
            with psycopg.connect(**connection_args,autocommit=True) as connection:
                role=connection.execute("SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()
                owner=connection.execute("SELECT pg_get_userbyid(datdba)=current_user FROM pg_database WHERE datname=current_database()").fetchone()
                if role is None or any(role) or owner != (True,):
                    raise CommandError("恢复目标必须由独立的低权限数据库所有者维护。")
                if not connection.execute("SELECT pg_try_advisory_lock(714293801)").fetchone()[0]:
                    raise CommandError("目标已有恢复任务，拒绝并发恢复。")
                nonempty=connection.execute("""SELECT EXISTS (
                    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                    UNION ALL SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                    UNION ALL SELECT 1 FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema')
                    UNION ALL SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                    UNION ALL SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql')""").fetchone()[0]
                if nonempty:
                    raise CommandError("恢复目标不是空数据库，拒绝覆盖；请创建新的隔离目标。")
                run_tool([tool,"--dbname="+target,"--no-owner","--no-acl","--single-transaction","--exit-on-error","--no-password"],env=pg_environment(db,database=target,user=target_user,password=password),stdin=stream,stdout=subprocess.DEVNULL)
        except psycopg.Error:
            raise CommandError("恢复目标连接或检查失败，未输出内部错误。") from None
