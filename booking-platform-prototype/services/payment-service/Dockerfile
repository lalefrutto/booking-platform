FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
# Все зависимости ставятся из готовых wheel-ов (psycopg2-binary, bcrypt, uvloop,
# httptools и т.д.), поэтому компилятор и dev-заголовки в образе не нужны —
# это убирает слой apt-get и делает сборку заметно быстрее и устойчивее.
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations

EXPOSE 8000

# Healthcheck на stdlib Python вместо curl — не тянем apt-пакеты в образ.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=10 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Схема БД накатывается миграциями Alembic, а не create_all при старте.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
