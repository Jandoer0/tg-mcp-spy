"""tg-mcp-spy — MCP-сервер для отслеживания Telegram-каналов и RSS/RSSHub лент.

Запускается как ASGI-приложение (streamable-http на /mcp) плюс веб-интерфейс
на /ui. Один порт — один контейнер.
"""
import os
from datetime import datetime, timezone, timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.prompts import base
from mcp.types import (
    ResourceTemplateReference,
    PromptReference,
    Completion,
    CompletionArgument,
    EmbeddedResource,
    TextResourceContents,
)

from db import (
    init_db,
    add_source,
    remove_source,
    list_sources,
    get_source,
    get_posts,
    rotate_if_needed,
    # «Мои темы»
    add_topic,
    remove_topic,
    get_topic,
    list_topics,
    reset_exclusions,
)
from rss_parser import rsshub_telegram_url, DEFAULT_RSSHUB
from webui import register_ui, _refresh_telegram, _refresh_rss
from agent import run_topic_agent
from scheduler import start_scheduler

RSSHUB_BASE_URL = os.environ.get("RSSHUB_BASE_URL", DEFAULT_RSSHUB)

mcp = MCPServer("Telegram Watcher")
init_db()
# При запуске — подчистить базу, если она уже превышает лимит размера.
rotate_if_needed()


# --------------------------------------------------------------------------- #
# Инструменты для Telegram (обратная совместимость)
# --------------------------------------------------------------------------- #
@mcp.tool()
def add_channel_tool(channelname: str) -> str:
    """Добавить Telegram-канал в список отслеживания"""
    channel = add_source("telegram", channelname)
    return f"Канал @{channel['name']} добавлен"


@mcp.tool()
def remove_channel_tool(channelname: str) -> str:
    """Удалить Telegram-канал из списка отслеживания"""
    name = channelname.strip().lower().lstrip("@")
    if remove_source(name):
        return f"Канал @{name} удалён"
    return f"Канал @{name} не найден"


@mcp.tool()
def list_channels_tool() -> str:
    """Показать список отслеживаемых Telegram-каналов"""
    channels = list_sources("telegram")
    if not channels:
        return "Нет отслеживаемых каналов"
    lines = [f"@{c['name']} (добавлен {c['added_at']})" for c in channels]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Общие инструменты для любых подписок (telegram + rss)
# --------------------------------------------------------------------------- #
@mcp.tool()
def add_source_tool(kind: str, name: str, url: str | None = None) -> str:
    """Добавить подписку.

    kind: "telegram" (тогда url не нужен) или "rss" (тогда нужен url ленты).
    Для Telegram через RSSHub используйте add_rsshub_channel_tool.
    """
    kind = kind.strip().lower()
    if kind not in ("telegram", "rss"):
        return "kind должен быть 'telegram' или 'rss'"
    if kind == "rss" and not url:
        return "Для rss нужно указать url"
    src = add_source(kind, name, url)
    return f"Подписка @{src['name']} ({src['kind']}) добавлена"


@mcp.tool()
def remove_source_tool(name: str) -> str:
    """Удалить любую подписку (Telegram или RSS) по имени"""
    n = name.strip().lower().lstrip("@")
    if remove_source(n):
        return f"Подписка @{n} удалена"
    return f"Подписка @{n} не найдена"


# --------------------------------------------------------------------------- #
# «Мои темы»: отслеживаемые темы и локальный ИИ-агент
# --------------------------------------------------------------------------- #
@mcp.tool()
def add_topic_tool(name: str, tag: str, schedule_minutes: int = 30, description: str = "") -> str:
    """Создать отслеживаемую тему «Мои темы» с тегом/меткой.

    Локальный ИИ-агент будет отбирать из общей ленты посты, относящиеся
    к теме (по тегу), и собирать их в хронологию темы. schedule_minutes —
    периодичность запуска агента для этой темы (в минутах). description —
    краткое пояснение, что именно имеется в виду под тегом (чтобы модель
    не отбирала всё подряд); держите его коротким, чтобы не раздувать
    контекст слабой модели.
    """
    res = add_topic(name, tag, schedule_minutes, description=description)
    if not res.get("ok"):
        return f"Ошибка: {res.get('error')}"
    return f"Тема «{res['name']}» (тег: {res['tag']}) создана"


@mcp.tool()
def remove_topic_tool(name: str) -> str:
    """Удалить отслеживаемую тему «Мои темы» (вместе с её хронологией)."""
    if remove_topic(name):
        return f"Тема «{name}» удалена"
    return f"Тема «{name}» не найдена"


@mcp.tool()
def reset_topic_exclusions_tool(name: str, post_id: int | None = None) -> str:
    """Снять признак исключения у темы «Мои темы» (вернуть посты агенту).

    Без post_id снимает все ручные исключения темы; с post_id — только для
    одного поста. После этого агент сможет снова отобрать пост(ы) при
    следующем прогоне. Это «явный сброс»: сам по себе агент не возвращает
    исключённые посты обратно в тему.
    """
    topic = get_topic(name)
    if not topic:
        return f"Тема «{name}» не найдена"
    removed = reset_exclusions(topic["id"], int(post_id) if post_id is not None else None)
    return f"Снято исключений: {removed}"


@mcp.tool()
def list_topics_tool() -> str:
    """Показать список отслеживаемых тем «Мои темы»."""
    topics = list_topics()
    if not topics:
        return "Нет отслеживаемых тем"
    lines = []
    for t in topics:
        state = "активна" if t.get("active") else "выкл."
        lines.append(
            f"• {t['name']} (тег: {t['tag']}, {state}, постов: {t.get('posts_count', 0)})"
        )
    return "\n".join(lines)


@mcp.tool()
def run_topic_agent_tool(name: str) -> str:
    """Запустить локального ИИ-агента для темы сейчас: отобрать релевантные посты."""
    topic = get_topic(name)
    if not topic:
        return f"Тема «{name}» не найдена"
    res = run_topic_agent(topic_id=topic["id"], max_batches=5)
    return (
        f"Тема «{name}»: просканировано {res.get('scanned', 0)}, "
        f"добавлено {res.get('added', 0)}, всего {res.get('total', 0)}"
    )


@mcp.tool()
def list_sources_tool() -> str:
    """Показать все подписки (Telegram и RSS)"""
    sources = list_sources()
    if not sources:
        return "Нет подписок"
    lines = [f"[{s['kind']}] @{s['name']}" + (f" -> {s['url']}" if s['url'] else "") for s in sources]
    return "\n".join(lines)


@mcp.tool()
def add_rsshub_channel_tool(username: str, base: str | None = None) -> str:
    """Добавить Telegram-канал через RSSHub (вместо прямого парсинга t.me).

    username — имя канала, base — адрес вашего RSSHub (по умолчанию публичный).
    """
    base = base or RSSHUB_BASE_URL
    url = rsshub_telegram_url(base, username)
    src = add_source("rss", username, url)
    return f"Канал @{src['name']} добавлен через RSSHub: {url}"


# --------------------------------------------------------------------------- #
# Получение постов
# (функции _refresh_telegram / _refresh_rss импортированы из webui)
# --------------------------------------------------------------------------- #
@mcp.tool()
def query_posts(sources: list[str] | None = None, days: int = 1) -> str:
    """Найти посты за последние N дней по подпискам (Telegram и RSS).

    Данные автоматически обновляются перед поиском.
    Если sources не указаны — берутся все подписки.
    """
    target = []
    if sources:
        for ch in sources:
            row = get_source(ch)
            if row:
                target.append(row)
            else:
                return f"Подписка @{ch} не отслеживается. Сначала добавьте её."
    else:
        target = list_sources()

    if not target:
        return "Нет подписок. Сначала добавьте канал или ленту."

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    for src in target:
        if src["kind"] == "telegram":
            _refresh_telegram(src, cutoff)
        else:
            _refresh_rss(src)

    result = get_posts([s["id"] for s in target], cutoff)
    if not result:
        days_label = "день" if days == 1 else "дня" if days < 5 else "дней"
        return f"Нет постов за последние {days} {days_label}"

    by_src: dict[str, list[dict]] = {}
    for p in result:
        by_src.setdefault(p["source"], []).append(p)

    parts = []
    for name, posts in by_src.items():
        parts.append(f"\n📢 @{name} ({len(posts)}):")
        for p in posts:
            preview = (p["text"][:200] + "…") if len(p["text"]) > 200 else p["text"]
            parts.append(f"[{p['date']}] {preview}")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Ресурсы и промпты (для агентов)
# --------------------------------------------------------------------------- #
@mcp.resource("tg://channels")
def channels_resource() -> str:
    """Список всех подписок (Telegram и RSS)"""
    sources = list_sources()
    if not sources:
        return "Нет подписок"
    lines = [f"[{s['kind']}] @{s['name']}" + (f" -> {s['url']}" if s['url'] else "") for s in sources]
    return "\n".join(lines)


@mcp.resource("tg://channel/{name}")
def channel_resource(name: str) -> str:
    """Информация об указанной подписке"""
    src = get_source(name)
    if not src:
        return f"Подписка @{name} не найдена"
    extra = f" -> {src['url']}" if src["url"] else ""
    return f"[{src['kind']}] @{src['name']}{extra} (добавлен {src['added_at']})"


@mcp.resource("tg://channel/{name}/posts")
def channel_posts_resource(name: str) -> str:
    """Последние посты подписки из кеша (без фетчинга)"""
    src = get_source(name)
    if not src:
        return f"Подписка @{name} не найдена"
    posts = get_posts([src["id"]], "1970-01-01")[:10]
    if not posts:
        return f"Нет постов в кеше для @{name}"
    parts = [f"@{name}:"]
    for p in posts:
        preview = (p["text"][:200] + "…") if len(p["text"]) > 200 else p["text"]
        parts.append(f"[{p['date']}] {preview}")
    return "\n".join(parts)


@mcp.prompt()
def digest(days: int = 7, channels: str | None = None):
    """Составить дайджест постов за последние N дней по подпискам"""
    instruction = (
        f"посмотри в методе query_posts(days={days}) посты "
        f"и составь дайджест по подпискам. "
        f"по каждой 2-3 предложения на главные темы. "
        f"Если подписок нет - сообщи об этом пользователю. "
        f"Если темы пересекаются - покажи один раз."
    )
    if channels is None:
        return [
            base.UserMessage(
                EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri="tg://channels",
                        text=channels_resource(),
                        mimeType="text/plain",
                    ),
                )
            ),
            base.UserMessage(instruction),
        ]
    return [base.UserMessage(f"Подписки: {channels}\n\n{instruction}")]


@mcp.completion()
async def complete_source_name(ref, argument: CompletionArgument, context) -> Completion | None:
    names = [s["name"] for s in list_sources()]
    if isinstance(ref, (ResourceTemplateReference, PromptReference)):
        return Completion(
            values=[n for n in names if n.lower().startswith(argument.value.lower())]
        )
    return None


# --------------------------------------------------------------------------- #
# Запуск
# --------------------------------------------------------------------------- #
def build_app():
    """Собрать ASGI-приложение: MCP (на /mcp) + веб-интерфейс (/ui, /api)."""
    register_ui(mcp)
    # Фоновый планировщик: авто-обновление ленты + периодический запуск агента.
    start_scheduler()
    if hasattr(mcp, "streamable_http_app"):
        return mcp.streamable_http_app(json_response=True)
    return mcp.http_app()  # запасной вариант для старых версий SDK


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(build_app(), host=host, port=port)
