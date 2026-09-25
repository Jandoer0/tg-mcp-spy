"""Сервис ИИ-редактора постов.

Глобальная (пакетная) и персональная (на лету) нормализация текста постов
через тот же локальный ИИ-провайдер, что и тематический агент. Хранит
оригал (`text`) и отредактированную версию (`text_edited`) + флаги
состояния (`editor_status`, `editor_active`) прямо в таблице posts.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Optional

from ..db import (
    delete_post_edited,
    get_post,
    get_posts,
    list_sources,
    set_post_edited,
    set_post_editor_status,
)
from . import agent

logger = logging.getLogger(__name__)

# Сколько постов за один пакетный прогон (как AGENT_BATCH).
EDITOR_BATCH = int(os.environ.get("EDITOR_BATCH", "10"))
# За сколько дней брать посты для пакетной обработки (0 = все).
EDITOR_DAYS = int(os.environ.get("EDITOR_DAYS", "7"))


def _text_of(post: dict) -> str:
    return (post.get("text") or "").strip()


def edit_one_post(post_id: int) -> dict:
    """Отредактировать один пост моделью. Возвращает сводку.

    Берёт оригинал (или уже активную редакцию как основу — нет, всегда
    оригинал, чтобы редакция не «накапливала» правки), прогоняет через
    модель, сохраняет text_edited и выставляет editor_status='done'.
    """
    post = get_post(post_id)
    if not post:
        return {"post_id": post_id, "ok": False, "error": "пост не найден"}
    original = _text_of(post)
    if not original:
        return {"post_id": post_id, "ok": False, "error": "пустой текст", "skipped": True}
    # Уже отредактирован и не требует повтора — пропускаем при пакетном прогоне,
    # но для явного персонального запуска обрабатываем заново.
    edited = agent.edit_text(original, model=_editor_model())
    if edited is None:
        set_post_editor_status(post_id, "none")
        return {
            "post_id": post_id,
            "ok": False,
            "error": "модель недоступна",
        }
    saved = set_post_edited(post_id, edited)
    return {
        "post_id": post_id,
        "ok": bool(saved),
        "edited_len": len(edited),
        "changed": edited.strip() != original,
    }


def _editor_provider() -> ProviderConfig:
    """Провайдер для ИИ-редактора."""
    from ..config import load_config, DEFAULT_PROVIDERS
    cfg = load_config()
    prov_name = cfg.editor_provider or "ollama"
    return cfg.providers.get(prov_name, DEFAULT_PROVIDERS["ollama"])


def _editor_model() -> Optional[str]:
    """Модель для ИИ-редактора."""
    from ..config import load_config
    cfg = load_config()
    m = (cfg.editor_model or "").strip()
    return m or None


def edit_post_async(post_id: int) -> None:
    """Запустить редактуру поста в фоновом потоке (не блокирует HTTP)."""

    def _t() -> None:
        try:
            set_post_editor_status(post_id, "editing")
            edit_one_post(post_id)
        except Exception as e:  # noqa: BLE001
            logger.error("Фоновая редактура поста %s упала: %s", post_id, e)
            try:
                set_post_editor_status(post_id, "none")
            except Exception:
                pass

    threading.Thread(target=_t, name="editor-post", daemon=True).start()


def run_editor_batch(days: Optional[int] = None, limit: Optional[int] = None) -> dict:
    """Пакетная обработка постов за последние N дней (или все).

    Пропускает уже отредактированные (editor_status='done') и пустые посты.
    Возвращает сводку: {"processed", "edited", "skipped", "errors", "error"}.
    """
    days = days if days is not None else EDITOR_DAYS
    since = "1970-01-01"
    if days and days > 0:
        from datetime import datetime, timedelta

        since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    srcs = list_sources()
    src_ids = [s["id"] for s in srcs]
    rows = get_posts(src_ids, since, limit=limit or 2000, offset=0)

    processed = 0
    edited = 0
    skipped = 0
    errors = 0
    for p in rows:
        pid = p["id"]
        # Пропускаем уже обработанные (повторный прогон не переписывает).
        if (p.get("editor_status") or "none") == "done":
            skipped += 1
            continue
        if not _text_of(p):
            skipped += 1
            continue
        processed += 1
        res = edit_one_post(pid)
        if res.get("ok"):
            if res.get("changed"):
                edited += 1
        else:
            errors += 1
    return {
        "processed": processed,
        "edited": edited,
        "skipped": skipped,
        "errors": errors,
    }


def run_editor_async(days: Optional[int] = None) -> None:
    """Запустить пакетную редактуру в фоновом потоке."""

    def _t() -> None:
        try:
            run_editor_batch(days=days)
        except Exception as e:  # noqa: BLE001
            logger.error("Фоновая пакетная редактура упала: %s", e)

    threading.Thread(target=_t, name="editor-batch", daemon=True).start()


def set_active(post_id: int, active: bool) -> bool:
    """Переключить показ оригинала/редакции для поста."""
    from ..db import set_post_editor_active

    return set_post_editor_active(post_id, active)


def remove_edition(post_id: int) -> bool:
    """Удалить сохранённую ИИ-редакцию поста (сброс флагов)."""
    return delete_post_edited(post_id)
