"""MCP-ресурсы — обзор подписок и последних постов (для агентов)."""
from __future__ import annotations

from ..db import get_posts, get_source, list_sources

from .server import mcp


@mcp.resource("tg://channels")
def channels_resource() -> str:
    """Список всех подписок (Telegram и RSS)"""
    sources = list_sources()
    if not sources:
        return "Нет подписок"
    lines = [
        f"[{s['kind']}] @{s['name']}" + (f" -> {s['url']}" if s["url"] else "")
        for s in sources
    ]
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
