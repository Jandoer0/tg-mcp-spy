"""Репозиторий подписок (sources): Telegram-каналы и RSS/RSSHub-ленты."""
from __future__ import annotations

from typing import Optional

from ..connection import get_conn, rotate_if_needed


def _norm(name: str) -> str:
    return name.strip().lower().lstrip("@")


def add_source(kind: str, name: str, url: Optional[str] = None) -> dict:
    name = _norm(name)
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
    name = _norm(name)
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
    """Подписки с id — нужно для пересборки постов (refresh)."""
    conn = get_conn()
    sql = "SELECT id, kind, name, url, added_at FROM sources ORDER BY name"
    params: list = []
    if kind:
        sql += " WHERE kind = ?"
        params.append(kind)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_source(name: str) -> Optional[dict]:
    name = _norm(name)
    conn = get_conn()
    row = conn.execute(
        "SELECT id, kind, name, url, added_at FROM sources WHERE name = ?", (name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_sources() -> list[dict]:
    return list_sources()


# --------------------------------------------------------------------------- #
# Обратная совместимость с оригинальными инструментами (только telegram)
# --------------------------------------------------------------------------- #
def add_channel(channelname: str) -> dict:
    return add_source("telegram", channelname)


def remove_channel(channelname: str) -> bool:
    return remove_source(channelname)


def list_channels() -> list[dict]:
    return list_sources("telegram")


def get_channel(channelname: str) -> Optional[dict]:
    return get_source(channelname)
