"""MCP-инструменты — тонкие обёртки над доменным ядром.

Каждая функция вызывает нужный слой (db / ingest / topics) и возвращает
строку для агента. Сами форматирование/логика — не здесь.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from mcp.server.mcpserver import MCPServer

from .. import ingest
from ..db import (
    add_source,
    get_posts,
    get_source,
    get_topic,
    list_sources,
    remove_source,
)
from ..ingest import rss
from ..topics import agent, service

from .server import mcp

RSSHUB_BASE_URL = "https://rsshub.app"


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
def add_topic_tool(
    name: str, tag: str, schedule_minutes: int = 1440, description: str = ""
) -> str:
    """Создать отслеживаемую тему «Мои темы» с тегом/меткой.

    Локальный ИИ-агент будет отбирать из общей ленты посты, относящиеся
    к теме (по тегу), и собирать их в хронологию темы. schedule_minutes —
    периодичность запуска агента (в минутах). description — краткое
    пояснение, что именно имеется в виду под тегом.
    """
    res = service.create_topic(name, tag, schedule_minutes, description=description)
    if not res.get("ok"):
        return f"Ошибка: {res.get('error')}"
    return f"Тема «{res['name']}» (тег: {res['tag']}) создана"


@mcp.tool()
def remove_topic_tool(name: str) -> str:
    """Удалить отслеживаемую тему «Мои темы» (вместе с хронологией)."""
    if service.delete_topic(name):
        return f"Тема «{name}» удалена"
    return f"Тема «{name}» не найдена"


@mcp.tool()
def reset_topic_exclusions_tool(name: str, post_id: int | None = None) -> str:
    """Снять признак исключения у темы «Мои темы» (вернуть посты агенту)."""
    if not get_topic(name):
        return f"Тема «{name}» не найдена"
    removed = service.reset_exclusions(name, int(post_id) if post_id is not None else None)
    return f"Снято исключений: {removed}"


@mcp.tool()
def list_topics_tool() -> str:
    """Показать список отслеживаемых тем «Мои темы»."""
    topics = list_sources_topics()
    if not topics:
        return "Нет отслеживаемых тем"
    lines = []
    for t in topics:
        state = "активна" if t.get("active") else "выкл."
        lines.append(
            f"• {t['name']} (тег: {t['tag']}, {state}, постов: {t.get('posts_count', 0)})"
        )
    return "\n".join(lines)


def list_sources_topics():
    from ..db import list_topics

    return list_topics()
    """Запустить локального ИИ-агента для темы сейчас."""
    res = service.run_agent(name, max_batches=5)
    if res.get("error"):
        return f"Тема «{name}»: {res['error']}"
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
    lines = [
        f"[{s['kind']}] @{s['name']}" + (f" -> {s['url']}" if s["url"] else "")
        for s in sources
    ]
    return "\n".join(lines)


@mcp.tool()
def add_rsshub_channel_tool(username: str, base: str | None = None) -> str:
    """Добавить Telegram-канал через RSSHub (вместо прямого парсинга t.me)."""
    base = base or RSSHUB_BASE_URL
    url = rss.rsshub_telegram_url(base, username)
    src = add_source("rss", username, url)
    return f"Канал @{src['name']} добавлен через RSSHub: {url}"


@mcp.tool()
def query_posts(sources: list[str] | None = None, days: int = 1) -> str:
    """Найти посты за последние N дней по подпискам (Telegram и RSS)."""
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
        ingest.refresh.refresh_source(src, days)

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


@mcp.tool()
def run_topic_agent_tool(name: str) -> str:
    """Запустить локального ИИ-агента для темы сейчас."""
    res = service.run_agent(name, max_batches=5)
    if res.get("error"):
        return f"Тема «{name}»: {res['error']}"
    return (
        f"Тема «{name}»: просканировано {res.get('scanned', 0)}, "
        f"добавлено {res.get('added', 0)}, всего {res.get('total', 0)}"
    )
