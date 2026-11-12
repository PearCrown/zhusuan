#!/bin/sh
# 生产启动脚本：先确认配置与数据库，再跑迁移和静态收集，最后交给 gunicorn。
# 迁移与 collectstatic 都幂等，重启安全；失败时容器/进程直接退出，不会带病启动。
set -eu

: "${DJANGO_SETTINGS_MODULE:=config.production}"
export DJANGO_SETTINGS_MODULE

echo "[start] check --deploy"
python manage.py check --deploy

echo "[start] 核对数据库连接"
python manage.py check_db

echo "[start] migrate"
python manage.py migrate --noinput

echo "[start] collectstatic"
python manage.py collectstatic --noinput --clear

echo "[start] gunicorn"
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-3}" \
  --timeout 60 \
  --access-logfile - \
  --error-logfile -
