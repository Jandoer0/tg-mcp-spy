"""Парсинг постов Telegram-каналов через публичный виджет t.me/s/<канал>."""
from __future__ import annotations

from typing import Optional

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://t.me/s"


def fetch_page(channel: str, before: Optional[int] = None) -> str:
    url = f"{BASE_URL}/{channel}"
    params = {}
    if before is not None:
        params["before"] = before

    resp = httpx.get(url, params=params, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    return resp.text


def _extract_message_text(node) -> str:
    """Извлечь читаемый текст сообщения из HTML Telegram-виджета.

    Сохраняет пробелы между словами (в т.ч. вокруг ссылок, хештегов,
    упоминаний), переводит ``<br>`` и абзацы ``<p>`` в переносы строк и
    убирает служебную HTML-разметку.
    """
    if node is None:
        return ""
    for br in node.find_all("br"):
        br.replace_with("\n")
    for p in node.find_all("p"):
        p.insert_after("\n")
    raw = node.get_text(separator="")
    raw = raw.replace("\u00a0", " ")
    lines = [" ".join(line.split()) for line in raw.split("\n")]
    return "\n".join(lines).strip()


def parse_posts(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    posts = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
        msg = wrap.select_one(".tgme_widget_message")
        if not msg:
            continue

        data_post = msg.get("data-post", "")
        if not data_post or "/" not in data_post:
            continue
        tg_post_id = int(data_post.split("/")[-1])

        text_elem = msg.select_one(".tgme_widget_message_text")
        text = _extract_message_text(text_elem)

        time_elem = msg.select_one("time")
        date_iso = time_elem.get("datetime", "")[:10] if time_elem else ""

        link_elem = msg.select_one("a.tgme_widget_message_date")
        url = link_elem.get("href", "") if link_elem else ""

        posts.append(
            {
                "ext_id": tg_post_id,
                "text": text,
                "date": date_iso,
                "url": url,
            }
        )
    return posts
