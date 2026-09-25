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


def get_posts(source_ids: list[int], since_date: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Посты подписок с даты ``since_date`` (не учитывая source_ids).

    Поддерживает пагинацию (limit/offset) для бесконечной прокрутки ленты.
    """
    if not source_ids:
        return []
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    conn = get_conn()
    n = len(source_ids)
    placeholders = ",".join(["?"] * n)
    sql = """
        SELECT p.id, s.name AS source, s.kind, p.ext_id, p.text, p.date, p.url
        FROM posts p JOIN sources s ON s.id = p.source_id
        WHERE s.id IN (%s)
          AND p.date >= ?
        ORDER BY p.id DESC
        LIMIT ? OFFSET ?
    """ % placeholders
    rows = conn.execute(sql, (*source_ids, since_date, limit, offset)).fetchall()
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


def get_posts_by_tag(tag: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Посты глобальной ленты, отмеченные тегом темы (фильтр по тегам)."""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    conn = get_conn()
    rows = conn.execute(
        """SELECT p.id AS id, p.source_id, p.ext_id, s.name AS source,
                  s.kind AS kind, p.text, p.date, p.url, pt.mode
           FROM posts_tags pt
           JOIN posts p ON p.id = pt.post_id
           JOIN sources s ON s.id = p.source_id
           JOIN topics t ON t.id = pt.topic_id
           WHERE t.tag = ?
           ORDER BY p.date DESC, p.id DESC LIMIT ? OFFSET ?""",
        (tag, limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_posts_by_tags(tags: list[str], limit: int = 50, offset: int = 0) -> list[dict]:
    """Посты, отмеченные СРАЗУ ВСЕМИ переданными тегами (логическое И).

    Используется для фильтрации пересекающихся тем (например, посты,
    имеющие и тег «Трамп», и тег «Си»).
    """
    tags = [t for t in (tags or []) if t]
    if not tags:
        return []
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    conn = get_conn()
    in_clauses = []
    params = []
    for t in tags:
        in_clauses.append(
            "p.id IN (SELECT pt.post_id FROM posts_tags pt "
            "JOIN topics tt ON tt.id = pt.topic_id WHERE tt.tag = ?)"
        )
        params.append(t)
    where = " AND ".join(in_clauses)
    sql = f"""
        SELECT p.id AS id, p.source_id, p.ext_id, s.name AS source,
               s.kind AS kind, p.text, p.date, p.url, '' AS mode
        FROM posts p
        JOIN sources s ON s.id = p.source_id
        WHERE {where}
        ORDER BY p.date DESC, p.id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_post(post_id: int) -> Optional[dict]:
    """Один пост по id (с полями ИИ-редактора)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, source_id, ext_id, text, text_edited, editor_status, "
        "editor_active, date, url FROM posts WHERE id = ?",
        (int(post_id),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def set_post_edited(post_id: int, text_edited: str) -> bool:
    """Сохранить отредактированную ИИ-версию и выставить editor_status='done'."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE posts SET text_edited = ?, editor_status = 'done' WHERE id = ?",
        (text_edited, int(post_id)),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def set_post_editor_status(post_id: int, status: str) -> bool:
    """Установить editor_status (например 'editing' во время обработки)."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE posts SET editor_status = ? WHERE id = ?",
        (status, int(post_id)),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def set_post_editor_active(post_id: int, active: bool) -> bool:
    """Переключить показ оригинала/редакции (editor_active)."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE posts SET editor_active = ? WHERE id = ?",
        (1 if active else 0, int(post_id)),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def delete_post_edited(post_id: int) -> bool:
    """Удалить сохранённую ИИ-редакцию, сбросить флаги."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE posts SET text_edited = NULL, editor_status = 'none', "
        "editor_active = 0 WHERE id = ?",
        (int(post_id),),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_posts_editor_status(post_ids: list) -> dict:
    """Вернуть {str(post_id): {status, active, has_edited}} для списка постов."""
    out: dict[str, dict] = {
        str(int(pid)): {"status": "none", "active": 0, "has_edited": False}
        for pid in post_ids
    }
    if not post_ids:
        return out
    placeholders = ",".join("?" * len(post_ids))
    conn = get_conn()
    rows = conn.execute(
        f"SELECT id, editor_status, editor_active, "
        f"CASE WHEN text_edited IS NOT NULL THEN 1 ELSE 0 END AS has_edited "
        f"FROM posts WHERE id IN ({placeholders})",
        [int(p) for p in post_ids],
    ).fetchall()
    conn.close()
    for r in rows:
        out[str(int(r["id"]))] = {
            "status": r["editor_status"] or "none",
            "active": int(r["editor_active"] or 0),
            "has_edited": bool(r["has_edited"]),
        }
    return out
