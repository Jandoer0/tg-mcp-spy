"""Пересборка постов из источников (Telegram t.me/s или RSS/RSSHub).

Логика раньше жила в ``webui.py``; вынесена в доменный слой ingest, чтобы
её могли вызывать и веб-маршруты, и MCP-инструменты, и планировщик — без
зависимости от транспортного слоя.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from ..db import get_oldest_post_date, save_posts
from . import rss, telegram


def refresh_telegram(source: dict, cutoff: str) -> None:
    """Подтянуть свежие посты Telegram-канала до даты ``cutoff`` (включительно)."""
    channelname = source["name"]
    before = None
    for _ in range(10):
        if before is not None:
            oldest = get_oldest_post_date(source["id"])
            if oldest and oldest < cutoff:
                break
        try:
            html = telegram.fetch_page(channelname, before)
        except Exception:
            break
        posts = telegram.parse_posts(html)
        if not posts:
            break
        save_posts(source["id"], posts)
        if posts[-1]["date"] and posts[-1]["date"] < cutoff:
            break
        before = posts[-1]["ext_id"]


def refresh_rss(source: dict) -> None:
    """Подтянуть посты из RSS/RSSHub-ленты источника."""
    try:
        content = rss.fetch_feed(source["url"])
    except Exception:
        return
    posts = rss.parse_feed(content)
    save_posts(source["id"], posts)


def refresh_source(source: dict, days: int = 1) -> bool:
    """Обновить один источник. Возвращает True при успехе."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        if source["kind"] == "telegram":
            refresh_telegram(source, cutoff)
        else:
            refresh_rss(source)
        return True
    except Exception:
        return False


def refresh_all_sources(days: int = 1, kind: str = "") -> dict:
    """Подтянуть свежие посты по всем (или выбранного типа) источникам."""
    from ..db import list_sources_with_id

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    sources = list_sources_with_id(kind) if kind else list_sources_with_id()
    ok, failed = 0, 0
    for src in sources:
        if refresh_source(src, days):
            ok += 1
        else:
            failed += 1
    return {"fetched": ok, "failed": failed, "days": days, "cutoff": cutoff}
