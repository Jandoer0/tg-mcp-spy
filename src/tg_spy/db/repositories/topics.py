"""Репозиторий «Мои темы»: темы, их хронология (posts_tags) и исключения."""
from __future__ import annotations

from typing import Optional

from ..connection import get_conn


def _norm(name: str) -> str:
    return name.strip().strip(" \t").lstrip("@")


def add_topic(
    name: str, tag: str, schedule_minutes: int = 1440, description: str = ""
) -> dict:
    """Создать (или обновить) отслеживаемую тему.

    ``description`` — краткое пояснение, что именно имеет в виду
    пользователь под тегом. Длина ограничена, чтобы не раздувать
    контекст модели.
    """
    name = _norm(name)
    tag = tag.strip()
    if not name:
        return {"ok": False, "error": "Укажите название темы"}
    if not tag:
        return {"ok": False, "error": "Укажите тег/метку темы"}
    description = (description or "").strip()[:300]
    try:
        schedule = max(1, int(schedule_minutes))
    except (TypeError, ValueError):
        schedule = 30
    conn = get_conn()
    conn.execute(
        """INSERT INTO topics (name, tag, description, schedule_minutes) VALUES (?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET
             tag=excluded.tag, description=excluded.description,
             schedule_minutes=excluded.schedule_minutes""",
        (name, tag, description, schedule),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, name, tag, description, active, schedule_minutes, "
        "last_post_id, last_run_at, created_at "
        "FROM topics WHERE name = ?",
        (name,),
    ).fetchone()
    conn.close()
    return {"ok": True, **dict(row)}


def get_topic(name: str) -> Optional[dict]:
    name = _norm(name)
    conn = get_conn()
    row = conn.execute("SELECT * FROM topics WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_topic_by_id(topic_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_topics() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """SELECT t.*,
                  (SELECT COUNT(*) FROM posts_tags pt WHERE pt.topic_id = t.id) AS posts_count
           FROM topics t ORDER BY t.name"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_topic(name: str) -> bool:
    n = _norm(name)
    conn = get_conn()
    row = conn.execute("SELECT id FROM topics WHERE name = ?", (n,)).fetchone()
    if not row:
        conn.close()
        return False
    # Явное удаление тегов темы (на случай, если FK выключены).
    conn.execute("DELETE FROM posts_tags WHERE topic_id = ?", (row["id"],))
    conn.execute("DELETE FROM topics WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return True


def set_topic_active(name: str, active: bool) -> bool:
    n = _norm(name)
    conn = get_conn()
    cur = conn.execute(
        "UPDATE topics SET active = ? WHERE name = ?", (1 if active else 0, n)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def update_topic_run(topic_id: int, last_post_id: Optional[int] = None) -> None:
    conn = get_conn()
    if last_post_id is not None:
        conn.execute(
            "UPDATE topics SET last_post_id = ?, last_run_at = datetime('now') WHERE id = ?",
            (int(last_post_id), topic_id),
        )
    else:
        conn.execute(
            "UPDATE topics SET last_run_at = datetime('now') WHERE id = ?", (topic_id,)
        )
    conn.commit()
    conn.close()


def tag_post(topic_id: int, post_id: int, mode: str = "ai") -> Optional[dict]:
    """Присвоить посту тег темы (mode='ai' — ИИ-агент, 'manual' — вручную)."""
    conn = get_conn()
    try:
        row = conn.execute(
            """SELECT p.id, s.name AS source, p.text, p.date, p.url
               FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ?""",
            (int(post_id),),
        ).fetchone()
        if not row:
            conn.close()
            return None
        conn.execute(
            "INSERT INTO posts_tags (post_id, topic_id, mode) VALUES (?, ?, ?) "
            "ON CONFLICT(post_id, topic_id) DO UPDATE SET mode=excluded.mode",
            (int(post_id), int(topic_id), mode),
        )
        # Явное присвоение тега снимает признак исключения.
        conn.execute(
            "DELETE FROM topic_exclusions WHERE topic_id = ? AND post_id = ?",
            (int(topic_id), int(post_id)),
        )
        conn.commit()
        conn.close()
        return dict(row)
    except Exception as e:
        import logging

        logging.getLogger(__name__).error("Ошибка присвоения тега: %s", e)
        conn.close()
        return None


def untag_post(topic_id: int, post_id: int) -> bool:
    """Снять тег темы с поста (удалить пост из темы вручную)."""
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM posts_tags WHERE topic_id = ? AND post_id = ?",
        (int(topic_id), int(post_id)),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def exclude_post(topic_id: int, post_id: int) -> bool:
    """Ручное удаление поста из темы + признак исключения."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO topic_exclusions (topic_id, post_id) VALUES (?, ?)",
            (int(topic_id), int(post_id)),
        )
        conn.execute(
            "DELETE FROM posts_tags WHERE topic_id = ? AND post_id = ?",
            (int(topic_id), int(post_id)),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        import logging

        logging.getLogger(__name__).error("Ошибка исключения поста: %s", e)
        conn.close()
        return False


def get_excluded_ids(topic_id: int, post_ids: list[int]) -> set[int]:
    """Множество исключённых post_id из переданного списка (для темы)."""
    if not post_ids:
        return set()
    conn = get_conn()
    placeholders = ",".join(["?"] * len(post_ids))
    rows = conn.execute(
        f"SELECT post_id FROM topic_exclusions WHERE topic_id = ? "
        f"AND post_id IN ({placeholders})",
        (int(topic_id), *post_ids),
    ).fetchall()
    conn.close()
    return {int(r["post_id"]) for r in rows}


def reset_exclusions(topic_id: int, post_id: int | None = None) -> int:
    """Снять признак исключения (для всей темы или одного поста)."""
    conn = get_conn()
    try:
        if post_id is None:
            cur = conn.execute(
                "DELETE FROM topic_exclusions WHERE topic_id = ?", (int(topic_id),)
            )
        else:
            cur = conn.execute(
                "DELETE FROM topic_exclusions WHERE topic_id = ? AND post_id = ?",
                (int(topic_id), int(post_id)),
            )
        conn.commit()
        n = cur.rowcount
        conn.close()
        return n
    except Exception as e:
        import logging

        logging.getLogger(__name__).error("Ошибка сброса исключений: %s", e)
        conn.close()
        return 0


def get_tagged_posts(topic_id: int, offset: int = 0, limit: int = 200) -> list[dict]:
    """Хронология темы — «движок» собирает посты, которым присвоен её тег."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT p.id AS id, p.source_id, p.ext_id, s.name AS source, p.text, p.date, p.url, pt.mode
           FROM posts_tags pt
           JOIN posts p ON p.id = pt.post_id
           JOIN sources s ON s.id = p.source_id
           WHERE pt.topic_id = ?
           ORDER BY p.date DESC, p.id DESC LIMIT ? OFFSET ?""",
        (int(topic_id), int(limit), int(offset)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tagged_total(topic_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM posts_tags WHERE topic_id = ?", (topic_id,)
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0
