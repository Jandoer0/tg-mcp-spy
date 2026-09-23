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
        -- «Мои темы»: отслеживаемая тема с тегом/меткой, по которой
        -- локальный ИИ-агент отбирает посты из общей ленты.
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            tag TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            schedule_minutes INTEGER NOT NULL DEFAULT 30,
            last_post_id INTEGER NOT NULL DEFAULT 0,
            last_run_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        -- Теги: какие посты (из общей ленты) относятся к теме. ИИ-агент
        -- *присваивает* тег (mode='ai'), пользователь — вручную (mode='manual').
        -- «Движок» сайта сам собирает посты с этим тегом в хронологию темы
        -- (см. get_tagged_posts): копирование в тему делает не модель, а
        -- движок, а модель только размечает посты тегами.
        CREATE TABLE IF NOT EXISTS posts_tags (
            post_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            mode TEXT NOT NULL DEFAULT 'ai',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
            FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
            UNIQUE(post_id, topic_id)
        );
        -- Исключения: посты, которые пользователь вручную удалил из темы.
        -- Агент НЕ должен автоматически возвращать их обратно — только по
        -- явному действию пользователя (повторное ручное добавление или
        -- сброс исключений через reset_exclusions). Хранится отдельно от
        -- posts_tags, чтобы не зависеть от наличия тега у поста.
        CREATE TABLE IF NOT EXISTS topic_exclusions (
            topic_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
            FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
            UNIQUE(topic_id, post_id)
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


# --------------------------------------------------------------------------- #
# Работа с «темами» (topics) и их хронологией (topic_posts)
# --------------------------------------------------------------------------- #
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


def add_topic(name: str, tag: str, schedule_minutes: int = 1440, description: str = "") -> dict:
    """Создать (или обновить) отслеживаемую тему.

    ``description`` — краткое пояснение, что именно имеет в виду пользователь
    под тегом (чтобы модель не отбирала всё подряд, а только релевантное).
    Длина ограничена, чтобы не раздувать контекст модели.
    """
    name = name.strip().strip(" \t").lstrip("@")
    tag = tag.strip()
    if not name:
        return {"ok": False, "error": "Укажите название темы"}
    if not tag:
        return {"ok": False, "error": "Укажите тег/метку темы"}
    # Ограничиваем описание, чтобы не раздувать контекст модели
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
        "SELECT id, name, tag, description, active, schedule_minutes, last_post_id, last_run_at, created_at "
        "FROM topics WHERE name = ?",
        (name,),
    ).fetchone()
    conn.close()
    return {"ok": True, **dict(row)}


def get_topic(name: str) -> Optional[dict]:
    name = name.strip().strip(" \t").lstrip("@")
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
    n = name.strip().strip(" \t").lstrip("@")
    conn = get_conn()
    row = conn.execute("SELECT id FROM topics WHERE name = ?", (n,)).fetchone()
    if not row:
        conn.close()
        return False
    # Явно удаляем теги темы (posts_tags). SQLite не включает foreign_keys
    # по умолчанию, поэтому каскад не сработает автоматически.
    conn.execute("DELETE FROM posts_tags WHERE topic_id = ?", (row["id"],))
    conn.execute("DELETE FROM topics WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return True


def set_topic_active(name: str, active: bool) -> bool:
    n = name.strip().strip(" \t").lstrip("@")
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
    """Присвоить посту тег темы (mode='ai' — ИИ-агент, 'manual' — вручную).

    Это «разметка» поста тегом; само копирование в хронологию темы выполняет
    «движок» (get_tagged_posts). То есть модель только *назначает теги*.
    """
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
        # Явное присвоение тега (ручное или ИИ) снимает признак исключения,
        # если он был выставлен при ручном удалении: пост теперь снова
        # принадлежит теме.
        conn.execute(
            "DELETE FROM topic_exclusions WHERE topic_id = ? AND post_id = ?",
            (int(topic_id), int(post_id)),
        )
        conn.commit()
        conn.close()
        return dict(row)
    except Exception as e:
        logger.error("Ошибка присвоения тега: %s", e)
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
    """Ручное удаление поста из темы + признак исключения.

    Пост убирается из хронологии темы И помечается как исключённый, чтобы
    локальный ИИ-агент больше не возвращал его автоматически. Вернуть его
    можно только явным действием пользователя: повторным ручным
    добавлением (снимет исключение) или сбросом исключений.
    """
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
        logger.error("Ошибка исключения поста: %s", e)
        conn.close()
        return False


def get_excluded_ids(topic_id: int, post_ids: list[int]) -> set[int]:
    """Множество исключённых post_id из переданного списка (для темы).

    Используется ИИ-агентом: перед присвоением тега посту он проверяет,
    не исключён ли пост вручную — и пропускает такие посты.
    """
    if not post_ids:
        return set()
    conn = get_conn()
    placeholders = ",".join(["?"] * len(post_ids))
    rows = conn.execute(
        f"SELECT post_id FROM topic_exclusions WHERE topic_id = ? AND post_id IN ({placeholders})",
        (int(topic_id), *post_ids),
    ).fetchall()
    conn.close()
    return {int(r["post_id"]) for r in rows}


def reset_exclusions(topic_id: int, post_id: int | None = None) -> int:
    """Снять признак исключения (для всей темы или одного поста).

    Это «явный сброс» пользователем: после него агент сможет снова
    отобрать пост(ы) при следующем прогоне (для ещё не просканированных
    постов). Возвращает число снятых исключений.
    """
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
        logger.error("Ошибка сброса исключений: %s", e)
        conn.close()
        return 0


def get_tagged_posts(topic_id: int, offset: int = 0, limit: int = 200) -> list[dict]:
    """Хронология темы — «движок» собирает посты, которым присвоен её тег.

    Возвращает посты из общей ленты, отмеченные тегом темы (mode='ai' или
    'manual'), упорядоченные по дате. Это и есть «копирование в тему», которое
    выполняет движок, а не модель.
    """
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


def get_posts_by_tag(tag: str, limit: int = 300) -> list[dict]:
    """Посты глобальной ленты, отмеченные тегом темы (фильтр по тегам).

    Используется выпадающим меню тегов во вкладке «Лента новостей»: показываем
    только те посты общей ленты, которым присвоен тег выбранной темы.
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT p.id AS id, p.source_id, p.ext_id, s.name AS source, p.text,
                  p.date, p.url, pt.mode
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
