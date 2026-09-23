-- Начальная схема: подписки, посты, «Мои темы» (темы + теги + исключения).
-- Идемпотентно (IF NOT EXISTS), поэтому безопасно применяется к уже
-- существующей базе. Таблица schema_version создаётся в коде.

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
-- «Движок» сайта сам собирает посты с этим тегом в хронологию темы.
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
-- явному действию пользователя.
CREATE TABLE IF NOT EXISTS topic_exclusions (
    topic_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
    UNIQUE(topic_id, post_id)
);
