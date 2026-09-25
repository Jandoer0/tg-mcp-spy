#!/usr/bin/env bash
#
# restart.sh — перезапуск проекта tg-mcp-spy «одной командой».
#
# Контейнер запускается от пользователя podman-svc через systemd-юнит
# tg-mcp-spy.service (quadlet-файл tg-mcp-spy.container). Скрипт:
#   1. тянет свежий образ из GitHub Container Registry
#      (ghcr.io/jandoer0/tg-mcp-spy:latest);
#   2. перезапускает юнит tg-mcp-spy.service.
#
# Запуск: ./restart.sh
#   Если выполняется НЕ от podman-svc — уходит по SSH к podman-svc
#   (ключ агента уже прописан в ~podman-svc/.ssh/authorized_keys).

set -euo pipefail

IMAGE="ghcr.io/jandoer0/tg-mcp-spy:latest"
UNIT="tg-mcp-spy.service"
REMOTE="podman-svc"

log() { echo "==> $*"; }

# Команды, которые выполняются от имени podman-svc (pull + restart юнита).
REMOTE_CMD="
set -e
podman pull '${IMAGE}'
systemctl --user restart '${UNIT}'
sleep 3
echo \"UNIT_STATUS=\$(systemctl --user is-active '${UNIT}')\"
"

if [ "$(id -un)" = "$REMOTE" ]; then
  log "Локально как $REMOTE: pull + restart $UNIT"
  bash -c "$REMOTE_CMD"
else
  log "Через ssh $REMOTE: pull + restart $UNIT"
  ssh -o BatchMode=yes "$REMOTE" "$REMOTE_CMD"
fi

log "Готово. Сервис должен отвечать на http://<host>:8091/ui"