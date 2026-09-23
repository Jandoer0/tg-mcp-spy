"""Хранение подписок и постов в SQLite.

Одна таблица ``sources`` описывает все подписки:
  * kind = "telegram"  -> канал Telegram, забираем через t.me/s/<name>
  * kind = "rss"       -> любая RSS/RSSHub лента, забираем по полю url

Таблица ``posts`` содержит кешированные посты по каждой подписке.
"""
import os
import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "telegram_cache.db")
# Максимальный размер базы в байтах (по умолчанию 100 МБ)
MAX_DB_BYTES = int(os.environ.get("MAX_DB_BYTES", str(100 * 1024 * 1024)))
# Каталог для БД создаём заранее, чтобы volume-монтирование не падало.
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Обычный rollback-журнал (а не WAL): при VACUUM физический размер
    # файла сразу уменьшается, и os.path.getsize(DB_PATH) — это точный
    # размер базы. WAL-режим держит данные в -wal файле и не сжимает
    # main-файл после VACUUM без явного checkpoint, что ломает ротацию.
    conn.execute("PRAGMA journal_mode=DELETE")
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
    rotate_if_needed()


def _get_db_size() -> int:
    """Физический размер файла базы на диске (в байтах).

    В режиме journal_mode=DELETE это точный размер данных — VACUUM
    сразу уменьшает файл, поэтому метрика надёжна для лимита.
    """
    try:
        return os.path.getsize(DB_PATH)
    except Exception:
        return 0


def rotate_if_needed() -> int:
    """Удалить самые старые посты, если база превысила MAX_DB_BYTES.

    Вызывается автоматически после save_posts и при старте сервера.
    Удаляются только посты (старые по полю date, затем id) — подписки
    (источники) не трогаются. После каждой пачки выполняется VACUUM,
    чтобы физически освободить место на диске. Цикл повторяется, пока
    размер базы (физический файл) не упадёт ниже 90% лимита (с запасом).

    Возвращает количество удалённых постов.
    """
    try:
        target_size = int(MAX_DB_BYTES * 0.9)
        deleted_total = 0
        conn = get_conn()
        # Ограничиваем число итераций, чтобы не уйти в бесконечный цикл
        # при экзотических ошибках. На практике хватает 1–3 итераций.
        for _ in range(50):
            current_size = _get_db_size()
            if current_size <= target_size:
                break
            total_posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            if total_posts == 0:
                break
            # Пачка: ~10% постов (минимум 1), чтобы не удалять всё сразу.
            batch = max(1, int(total_posts * 0.10))
            batch = min(batch, total_posts)
            conn.execute(
                """DELETE FROM posts WHERE id IN (
                       SELECT id FROM posts ORDER BY date ASC, id ASC LIMIT ?
                   )""",
                (batch,),
            )
            conn.commit()
            # VACUUM физически сжимает файл базы (в режиме DELETE-журнала
            # размер файла сразу уменьшается).
            conn.execute("VACUUM")
            conn.commit()
            deleted_total += batch
        conn.close()
        if deleted_total:
            logger.info(
                "Ротация БД: удалено %d постов (лимит %d байт)",
                deleted_total, MAX_DB_BYTES,
            )
        return deleted_total
    except Exception as e:
        logger.error("Ошибка ротации БД: %s", e)
        return 0


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
