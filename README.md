# tg-mcp-spy

MCP-сервер для отслеживания **Telegram-каналов** и **RSS/RSSHub-лент** с веб-интерфейсом
для управления подписками.

Возможности:
- добавление/удаление подписок на Telegram-каналы (через публичный виджет `t.me/s/...`);
- добавление подписок через **RSSHub** и любые RSS-ленты;
- веб-интерфейс для управления списком подписок и просмотра постов;
- запуск в контейнере через `podman compose` (порт 8090);
- нативная работа с агентами **Hermes** и **pi.dev** (конфиг в `.mcp.json`).

## Быстрый старт

```bash
podman compose build     # собрать образ (первый раз и после правок)
podman compose up -d     # запустить в фоне, веб на http://localhost:8090/ui
```

Полезные команды:

| Команда | Что делает |
|---------|------------|
| `podman compose build` | собрать образ контейнера |
| `podman compose up -d` | запустить (порт 8090) |
| `podman compose down` | остановить |
| `podman compose down && podman compose up -d` | перезапустить (при правках кода) |
| `podman compose logs -f` | показывать логи |
| `podman compose ps` | статус контейнера |

Второй независимый экземпляр на другом порту:

```bash
HOST_PORT=8091 podman compose up -d
```

## Образ и GitHub Container Registry

Образ собирается автоматически в GitHub Actions (`.github/workflows/build.yml`)
при каждом пуше в `master` и публикуется в GitHub Container Registry:
`ghcr.io/jandoer0/tg-mcp-spy:latest`. На сервере образ **не собирается** —
`compose.yaml` и `./run.sh start` просто подтягивают его готовым.

- Обновить образ вручную: `./run.sh pull` (или `podman compose pull`).
- Локальная сборка остаётся как запасной вариант: `./run.sh build`
  (соберёт образ из исходников прямо на этом сервере).

⚠️ В репозитории должны быть включены GitHub Actions
(Settings → Actions → General → Allow all actions). Первая публикация образа
происходит автоматически после первого пуша; до этого `podman compose pull`
будет недоступен (образа ещё нет в реестре).

Данные (база SQLite) хранятся в каталоге `./data` на хосте и не теряются
между перезапусками.

## Развёртывание на удалённом сервере (podman quadlet)

Продакшен крутится на сервере `podman-svc@<SERVER_IP>` через **podman quadlet**
(файл `tg-mcp-spy.container`, systemd-юнит `tg-mcp-spy.service`, порт `8091`).
Сборка образа выполняется автоматически в GitHub Actions (`.github/workflows/build.yml`) при каждом пуше в `master` и публикуется в GHCR. На сервере образ подтягивается готовым,
поэтому после правок достаточно обновить контейнер одной командой:

```bash
./run.sh deploy        # обновить серверный контейнер свежим образом из GHCR (rupdate)
```

Остальные удалённые команды: `rrestart`, `rstart`, `rstop`, `rstatus`,
`rlogs`, `rshell`, `rreload` (см. `./run.sh help`).

### Парольная фраза SSH-ключа

Ключ `<PATH_TO_SSH_KEY>` защищён парольной фразой. Чтобы скрипт
подключался без повторного ввода, добавьте ключ в **OpenSSH Authentication Agent**
(фраза хранится в Windows Credential Manager и переживает перезагрузку):

```powershell
Set-Service ssh-agent -StartupType Automatic
Start-Service ssh-agent
ssh-add <PATH_TO_SSH_KEY>   # спросит фразу один раз
```

Если меняли `tg-mcp-spy.container` на сервере — примените `./run.sh rreload`.

## Веб-интерфейс

Откройте в браузере: **http://localhost:8090/ui**



Там можно:
- видеть список всех подписок (Telegram и RSS) с бейджами;
- добавить Telegram-канал по имени (без `@`);
- добавить канал через RSSHub (если `t.me` недоступен);
- добавить произвольную RSS/RSSHub-ленту по ссылке;
- удалять подписки и просматривать последние посты.

## Работа с агентами (Hermes, pi.dev)

MCP-сервер доступен по адресу `http://127.0.0.1:8090/mcp` (streamable-http, один порт).
Готовый конфиг лежит в `.mcp.json` — клиенты вроде **pi.dev** подхватят его автоматически.

### Hermes agent

Кратко:
откройте `~/.hermes/config.yaml`, в раздел `mcp_servers:` добавьте:

```yaml
mcp_servers:
  tg-mcp-spy:
    url: "http://127.0.0.1:8090/mcp"
```

Перезапустите Hermes Agent и проверьте: `hermes mcp list`. Инструменты
появятся с префиксом `mcp_tg_mcp_spy_*`.

### pi.dev

Используйте готовый `.mcp.json` (указывает на `http://127.0.0.1:8090/mcp`).
При необходимости добавьте MCP-сервер в настройках проекта pi.dev с тем же URL.

Основные инструменты для агента:
- `add_channel_tool` / `remove_channel_tool` / `list_channels_tool` — Telegram;
- `add_rsshub_channel_tool` — добавить канал через RSSHub;
- `add_source_tool` / `remove_source_tool` / `list_sources_tool` — любые подписки;
- `query_posts` — получить свежие посты за N дней по всем/выбранным подпискам;
- ресурсы `tg://channels`, `tg://channel/{name}`, `tg://channel/{name}/posts`;
- промпт `digest` — составить дайджест.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `HOST` | `0.0.0.0` | адрес внутри контейнера |
| `PORT` | `8000` | порт внутри контейнера |
| `DB_PATH` | `/app/data/telegram_cache.db` | путь к базе |
| `RSSHUB_BASE_URL` | `https://rsshub.app` | база RSSHub (можно своя) |

## Как это работает

Сервер опрашивает источники и кеширует посты в локальной SQLite-базе:
- Telegram-канал — через HTML-виджет `https://t.me/s/<канал>` (пагинация по `before`);
- RSS/RSSHub — через скачивание и разбор RSS/Atom (`feedparser`).

Один контейнер, один порт: на нём и MCP (`/mcp`), и веб-интерфейс (`/ui`).
