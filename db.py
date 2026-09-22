"""Хранение подписок и постов в SQLite.

Одна таблица ``sources`` описывает все подписки:
  * kind = "telegram"  -> канал Telegram, забираем через t.me/s/<name>
  * kind = "rss"       -> любая RSS/RSSHub лента, забираем по полю url

Таблица ``posts`` содержит кешированные посты по каждой подписке.
"""
import os
import sqlite3
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "telegram_cache.db")
# Каталог для БД создаём заранее, чтобы volume-монтирование не падало.
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK (kind IN ('telegram', 'rss')),
            name TEXT UNIQUE NOT NULL,
            url TEXT,
            added_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            ext_id TEXT NOT NULL,
            text TEXT,
            date TEXT NOT NULL,
            url TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            UNIQUE(source_id, ext_id)
        );
    """)
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# Работа с подписками (sources)
# --------------------------------------------------------------------------- #
def add_source(kind: str, name: str, url: Optional[str] = None) -> dict:
    name = name.strip().lower().lstrip("@")
    conn = get_conn()
    conn.execute(
        """INSERT INTO sources (kind, name, url) VALUES (?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, url=excluded.url""",
        (kind, name, url),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, kind, name, url, added_at FROM sources WHERE name = ?", (name,)
    ).fetchone()
    conn.close()
    return dict(row)


def remove_source(name: str) -> bool:
    name = name.strip().lower().lstrip("@")
    conn = get_conn()
    row = conn.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("DELETE FROM posts WHERE source_id = ?", (row["id"],))
    conn.execute("DELETE FROM sources WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return True


def list_sources(kind: Optional[str] = None) -> list[dict]:
    conn = get_conn()
    if kind:
        rows = conn.execute(
            "SELECT id, kind, name, url, added_at FROM sources WHERE kind = ? ORDER BY name",
            (kind,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, kind, name, url, added_at FROM sources ORDER BY name"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_sources_with_id(kind: Optional[str] = None) -> list[dict]:
    """Возвращает подписки с id — нужно для пересборки постов (refresh)."""
    conn = get_conn()
    sql = "SELECT id, kind, name, url, added_at FROM sources ORDER BY name"
    params = []
    if kind:
        sql += " WHERE kind = ?"
        params.append(kind)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_source(name: str) -> Optional[dict]:
    name = name.strip().lower().lstrip("@")
    conn = get_conn()
    row = conn.execute(
        "SELECT id, kind, name, url, added_at FROM sources WHERE name = ?", (name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_sources() -> list[dict]:
    return list_sources()


# Обратная совместимость с оригинальными инструментами (только telegram)
def add_channel(channelname: str) -> dict:
    return add_source("telegram", channelname)


def remove_channel(channelname: str) -> bool:
    return remove_source(channelname)


def list_channels() -> list[dict]:
    return list_sources("telegram")


def get_channel(channelname: str) -> Optional[dict]:
    return get_source(channelname)


# --------------------------------------------------------------------------- #
# Работа с постами (posts)
# --------------------------------------------------------------------------- #
def save_posts(source_id: int, posts: list[dict]):
    conn = get_conn()
    for post in posts:
        conn.execute(
            """INSERT OR IGNORE INTO posts (source_id, ext_id, text, date, url)
               VALUES (?, ?, ?, ?, ?)""",
            (source_id, str(post["ext_id"]), post["text"], post["date"], post["url"]),
        )
    conn.commit()
    conn.close()


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
