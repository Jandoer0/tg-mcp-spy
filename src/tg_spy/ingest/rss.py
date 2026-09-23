"""Работа с RSS и RSSHub лентами.

RSSHub — это сервис, который умеет отдавать RSS для сайтов, у которых нет
родной ленты. Например, для Telegram-канала:
    https://rsshub.app/telegram/channel/durov
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from bs4 import BeautifulSoup

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
    return ""


def _html_to_text(html: str) -> str:
    """Превратить HTML-содержимое RSS/Atom в чистый текст."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["p", "div"]):
        tag.insert_after("\n")
    raw = soup.get_text(separator="")
    raw = raw.replace("\u00a0", " ")
    lines = [" ".join(line.split()) for line in raw.split("\n")]
    return "\n".join(lines).strip()


def parse_feed(content: str) -> list[dict]:
    parsed = feedparser.parse(content)
    posts = []
    for entry in parsed.entries:
        link = entry.get("link", "")
        guid = entry.get("guid") or link
        title = entry.get("title", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        summary_text = _html_to_text(summary)
        text = (title + "\n\n" + summary_text).strip() if (title or summary_text) else ""
        posts.append(
            {
                "ext_id": guid or link,
                "text": text,
                "date": _parse_date(entry),
                "url": link,
            }
        )
    return posts
