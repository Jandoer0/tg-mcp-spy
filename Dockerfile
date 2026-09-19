FROM python:3.14-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Зависимости (есть готовые wheel-ы, компиляция не нужна)
RUN pip install --no-cache-dir \
    "mcp[cli]>=1.27.2" \
    "beautifulsoup4>=4.13" \
    "lxml>=5.3" \
    "httpx>=0.27" \
    "feedparser>=6.0" \
    "starlette>=0.37" \
    "uvicorn>=0.30"

COPY . .

ENV HOST=0.0.0.0 \
    PORT=8000 \
    DB_PATH=/app/data/telegram_cache.db \
    RSSHUB_BASE_URL=https://rsshub.app

EXPOSE 8000
CMD ["python", "main.py"]
