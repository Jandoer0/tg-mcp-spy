FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

# Зависимости (wheel-ы готовы, компиляция не нужна).
# Сначала манифест + исходники пакета, чтобы слой кеша зависел только от кода.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Остальные файлы (конфиги, Dockerfile-игнорируемое не копируется).
COPY . .

# Непривилегированный пользователь.
RUN useradd -m -u 10001 appuser \
    && mkdir -p /app/data && chown -R appuser /app
USER appuser

ENV HOST=0.0.0.0 \
    PORT=8000 \
    DB_PATH=/app/data/telegram_cache.db \
    RSSHUB_BASE_URL=https://rsshub.app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/sources').status==200 else 1)" || exit 1

CMD ["python", "-m", "tg_spy", "serve"]
