"""Парсинг постов Telegram-каналов через публичный виджет t.me/s/<канал>."""
import httpx
from bs4 import BeautifulSoup
from typing import Optional

BASE_URL = "https://t.me/s"


def fetch_page(channel: str, before: Optional[int] = None) -> str:
    url = f"{BASE_URL}/{channel}"
    params = {}
    if before is not None:
        params["before"] = before

    resp = httpx.get(url, params=params, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    return resp.text


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
        text = text_elem.get_text(strip=True) if text_elem else ""

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
