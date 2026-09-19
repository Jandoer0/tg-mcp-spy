#!/usr/bin/env bash
# Управление tg-mcp-spy: сборка, запуск, перезапуск, логи, локальная отладка.
# Работает под обычным пользователем (rootless podman), sudo не нужен.
set -euo pipefail

cd "$(dirname "$0")"

# Цвета для вывода
g='\033[0;32m'; y='\033[0;33m'; r='\033[0;31m'; n='\033[0m'
info()  { echo -e "${g}▶${n} $*"; }
warn()  { echo -e "${y}•${n} $*"; }
err()   { echo -e "${r}✗${n} $*" >&2; }

# Порт на хосте (по умолчанию 8090; для второго экземпляра — 8091 и т.д.)
HOST_PORT="${HOST_PORT:-8090}"

# Проект и каталог данных привязаны к порту, чтобы можно было поднять
# несколько независимых экземпляров (8090, 8091, ...).
resolve() {
  local p="${1:-$HOST_PORT}"
  PORT="$p"
  PROJECT="tg-mcp-spy-$p"
  DATA_DIR="${DATA_DIR:-./data-$p}"
}

usage() {
  cat <<EOF
Использование: ./run.sh <команда> [порт]

Команды:
  build       собрать образ контейнера
  start [порт]   запустить в фоне (по умолчанию порт 8090)
  stop        остановить контейнер
  restart [порт] перезапустить (удобно при правках)
  logs        показывать логи (Ctrl+C — выход)
  status      статус контейнера
  shell       зайти внутрь контейнера (bash)
  dev [порт]  локальный запуск без контейнера (для отладки кода)
  help        эта справка

Примеры:
  ./run.sh start            # http://localhost:8090/ui
  ./run.sh restart 8091     # второй экземпляр на порту 8091
  ./run.sh dev              # локально на 127.0.0.1:8000
EOF
}

need_podman() {
  if ! command -v podman >/dev/null 2>&1; then
    err "Не найден podman. Установите podman и podman-compose."
    exit 1
  fi
}

cmd_build() {
  need_podman
  info "Сборка образа tg-mcp-spy…"
  podman compose build
  info "Готово."
}

cmd_start() {
  need_podman
  resolve "${1:-}"
  HOST_PORT="$PORT" DATA_DIR="$DATA_DIR" podman compose -p "$PROJECT" up -d
  info "Запущено. Веб-интерфейс: http://localhost:${PORT}/ui"
  info "MCP-эндпоинт:        http://localhost:${PORT}/mcp"
}

cmd_stop() {
  need_podman
  resolve "${1:-}"
  podman compose -p "$PROJECT" down
  info "Остановлено (порт ${PORT})."
}

cmd_restart() {
  need_podman
  resolve "${1:-}"
  podman compose -p "$PROJECT" down >/dev/null 2>&1 || true
  HOST_PORT="$PORT" DATA_DIR="$DATA_DIR" podman compose -p "$PROJECT" up -d
  info "Перезапущено на порту ${PORT}."
}

cmd_logs() {
  need_podman
  resolve "${1:-}"
  podman compose -p "$PROJECT" logs -f
}

cmd_status() {
  need_podman
  resolve "${1:-}"
  podman compose -p "$PROJECT" ps
}

cmd_shell() {
  need_podman
  resolve "${1:-}"
  podman compose -p "$PROJECT" exec tg-mcp-spy bash || podman compose -p "$PROJECT" run --rm tg-mcp-spy bash
}

cmd_dev() {
  warn "Локальный режим (без контейнера). Для отладки кода."
  PORT="${1:-8000}"
  DATA_DIR="${DATA_DIR:-./data-dev}"
  mkdir -p "$DATA_DIR"
  if [ ! -d .venv ]; then
    info "Создание виртуального окружения .venv…"
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  info "Установка зависимостей…"
  pip install --quiet --upgrade pip
  pip install --quiet \
    "mcp[cli]>=1.27.2" "beautifulsoup4>=4.13" "lxml>=5.3" \
    "httpx>=0.27" "feedparser>=6.0" "starlette>=0.37" "uvicorn>=0.30"
  export HOST=127.0.0.1 PORT="$PORT" DB_PATH="$DATA_DIR/dev_cache.db"
  info "Запуск на http://127.0.0.1:${PORT}/ui (Ctrl+C — стоп)"
  python main.py
}

main() {
  local cmd="${1:-help}"; shift || true
  case "$cmd" in
    build)   cmd_build ;;
    start)   cmd_start "${1:-$HOST_PORT}" ;;
    stop)    cmd_stop ;;
    restart) cmd_restart "${1:-$HOST_PORT}" ;;
    logs)    cmd_logs ;;
    status)  cmd_status ;;
    shell)   cmd_shell ;;
    dev)     cmd_dev "${1:-}" ;;
    help|-h|--help) usage ;;
    *) err "Неизвестная команда: $cmd"; usage; exit 1 ;;
  esac
}

main "$@"
