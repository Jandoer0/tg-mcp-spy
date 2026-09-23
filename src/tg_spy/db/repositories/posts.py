"""Репозиторий постов (posts): кеш общей ленты и ротация по лимиту."""
from __future__ import annotations

from typing import Optional

from ..connection import get_conn, rotate_if_needed


def save_posts(source_id: int, posts: list[dict]) -> None:
    conn = get_conn()
    for post in posts:
        conn.execute(
            """INSERT OR IGNORE INTO posts (source_id, ext_id, text, date, url)
               VALUES (?, ?, ?, ?, ?)""",
            (source_id, str(post["ext_id"]), post["text"], post["date"], post["url"]),
        )
    conn.commit()
    conn.close()
    rotate_if_needed()


def get_oldest_post_date(source_id: int) -> Optional[str]:
    conn = get_conn()
    row = conn.execute(
        "SELECT MIN(date) as min_date FROM posts WHERE source_id = ?", (source_id,)
    ).fetchone()
    conn.close()
    return row["min_date"] if row and row["min_date"] is not None else None


def get_posts(source_ids: list[int], since_date: str) -> list[dict]:
    """Посты подписок с даты ``since_date`` (не учитывая source_ids)."""
    if not source_ids:
        return []
    conn = get_conn()
    n = len(source_ids)
    placeholders = ",".join(["?"] * n)
    sql = """
        SELECT p.id, s.name AS source, s.kind, p.ext_id, p.text, p.date, p.url
        FROM posts p JOIN sources s ON s.id = p.source_id
        WHERE s.id IN (%s)
          AND p.date >= ?
        ORDER BY p.date DESC, p.ext_id DESC
    """ % placeholders
    rows = conn.execute(sql, (*source_ids, since_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_posts_after(post_id: int, limit: int = 60) -> list[dict]:
    """Посты с id > post_id (новые для темы), по возрастанию id.

    Используется ИИ-агентом для поэтапного сканирования ленты: поле
    ``last_post_id`` темы — это high-water mark уже обработанных постов.
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT p.id, s.name AS source, s.kind, p.source_id, p.ext_id, p.text, p.date, p.url
           FROM posts p JOIN sources s ON s.id = p.source_id
           WHERE p.id > ? ORDER BY p.id ASC LIMIT ?""",
        (int(post_id), int(limit)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_posts_by_tag(tag: str, limit: int = 300) -> list[dict]:
    """Посты глобальной ленты, отмеченные тегом темы (фильтр по тегам)."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT p.id AS id, p.source_id, p.ext_id, s.name AS source,
                  s.kind AS kind, p.text, p.date, p.url, pt.mode
           FROM posts_tags pt
           JOIN posts p ON p.id = pt.post_id
           JOIN sources s ON s.id = p.source_id
           JOIN topics t ON t.id = pt.topic_id
           WHERE t.tag = ?
           ORDER BY p.date DESC, p.id DESC LIMIT ?""",
        (tag, int(limit)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
