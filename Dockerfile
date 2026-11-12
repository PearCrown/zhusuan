# 生产镜像：只装运行依赖，不在镜像里烤进任何秘密或数据库。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.production

WORKDIR /app

# 先装依赖，代码改动不会让这一层失效
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

# 运行用户不能是 root；静态文件与数据库连接都在运行时准备
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8000
# 迁移、collectstatic、健康检查与 gunicorn 都在这里，需在运行时注入环境变量
CMD ["./scripts/start-production.sh"]
