-- ИИ-редактор постов: оригинал (text) + отредактированная версия
-- (text_edited) и флаги состояния. Идемпотентно (IF NOT EXISTS на уровне
-- проверки существования колонки), безопасно при повторном применении.

ALTER TABLE posts ADD COLUMN text_edited TEXT;
ALTER TABLE posts ADD COLUMN editor_status TEXT NOT NULL DEFAULT 'none';  -- none | editing | done
ALTER TABLE posts ADD COLUMN editor_active INTEGER NOT NULL DEFAULT 0;     -- 1 = показывать text_edited
