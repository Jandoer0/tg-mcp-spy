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
    save_posts,
    get_oldest_post_date,
    get_posts,
)
from tg_parser import fetch_page, parse_posts
from rss_parser import fetch_feed, parse_feed, rsshub_telegram_url, DEFAULT_RSSHUB
from webui import register_ui

RSSHUB_BASE_URL = os.environ.get("RSSHUB_BASE_URL", DEFAULT_RSSHUB)

mcp = MCPServer("Telegram Watcher")
init_db()


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
# --------------------------------------------------------------------------- #
def _refresh_telegram(source: dict, cutoff: str):
    channelname = source["name"]
    before = None
    for _ in range(10):
        if before is not None:
            oldest = get_oldest_post_date(source["id"])
            if oldest and oldest < cutoff:
                break
        try:
            html = fetch_page(channelname, before)
        except Exception:
            break
        posts = parse_posts(html)
        if not posts:
            break
        save_posts(source["id"], posts)
        if posts[-1]["date"] and posts[-1]["date"] < cutoff:
            break
        before = posts[-1]["ext_id"]


def _refresh_rss(source: dict):
    try:
        content = fetch_feed(source["url"])
    except Exception:
        return
    posts = parse_feed(content)
    save_posts(source["id"], posts)


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
    if hasattr(mcp, "streamable_http_app"):
        return mcp.streamable_http_app(json_response=True)
    return mcp.http_app()  # запасной вариант для старых версий SDK


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(build_app(), host=host, port=port)
