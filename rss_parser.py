"""Работа с RSS и RSSHub лентами.

RSSHub — это сервис, который умеет отдавать RSS для сайтов, у которых нет
родной ленты. Например, для Telegram-канала:
    https://rsshub.app/telegram/channel/durov

Мы просто скачиваем URL и парсим стандартный RSS/Atom.
"""
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import feedparser

DEFAULT_RSSHUB = "https://rsshub.app"


def rsshub_telegram_url(base: str, username: str) -> str:
    """Собрать RSSHub-ссылку на Telegram-канал."""
    username = username.strip().lower().lstrip("@")
    return f"{base.rstrip('/')}/telegram/channel/{username}"


def fetch_feed(url: str) -> str:
    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (tg-mcp-spy)"},
    )
    resp.raise_for_status()
    return resp.text


def _parse_date(entry: dict) -> str:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if isinstance(val, time.struct_time):
            return datetime(*val[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d")
    # Если не распарсили — вернём пусто (пост уйдёт в конец выдачи)
    return ""


def parse_feed(content: str) -> list[dict]:
    parsed = feedparser.parse(content)
    posts = []
    for entry in parsed.entries:
        link = entry.get("link", "")
        guid = entry.get("guid") or link
        title = entry.get("title", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        text = (title + "\n\n" + summary).strip() if (title or summary) else ""
        posts.append(
            {
                "ext_id": guid or link,
                "text": text,
                "date": _parse_date(entry),
                "url": link,
            }
        )
    return posts
