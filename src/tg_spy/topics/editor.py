"""Сервис ИИ-редактора постов.

Глобальная (пакетная) и персональная (на лету) нормализация текста постов
через тот же локальный ИИ-провайдер, что и тематический агент. Хранит
оригал (`text`) и отредактированную версию (`text_edited`) + флаги
состояния (`editor_status`, `editor_active`) прямо в таблице posts.
"""
from __future__ import annotations

import logging
import os
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
from ..config import load_config
from .provider import call_role, last_provider_error

logger = logging.getLogger(__name__)

# Сколько постов за один пакетный прогон (как AGENT_BATCH).
EDITOR_BATCH = int(os.environ.get("EDITOR_BATCH", "10"))
# За сколько дней брать посты для пакетной обработки (0 = все).
EDITOR_DAYS = int(os.environ.get("EDITOR_DAYS", "7"))


def _edit_result(text: str, max_chars: int = 4000, model: Optional[str] = None):
    """Вызвать модель редактора через единую ролевую логику (call_role).

    Возвращает полный результат (в т.ч. флаг `aborted` — прерывание
    пользователем), чтобы пакетная обработка могла остановиться сразу.
    """
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > max_chars:
        text = text[:max_chars]
    cfg = load_config()
    return call_role(
        "editor",
        [
            {"role": "system", "content": cfg.editor_system_prompt},
            {"role": "user", "content": text},
        ],
        temperature=0.0,
        output_format="text",  # редактор возвращает Markdown, а не JSON
        model=model,
        abortable=True,
    )


def edit_text(text: str, max_chars: int = 4000, model: Optional[str] = None) -> Optional[str]:
    """Прогнать текст поста через ИИ-редактора (роль 'editor').

    Возвращает отредактированный текст или None при недоступности модели.
    Использует единую для обеих ролей логику :func:`provider.call_role`
    (как и классификатор): свой провайдер/модель из конфига, общие повторы,
    ошибки и прерывание. Для диагностики — :func:`last_provider_error('editor')`
    (тот же механизм и тексты, что у классификатора).
    """
    result = _edit_result(text, max_chars=max_chars, model=model)
    if result is None or not result.ok:
        return None
    return result.content or None


def last_editor_error() -> Optional[str]:
    """Последняя ошибка провайдера редактора (для уведомлений в UI).

    Тот же механизм, что у классификатора (:func:`provider.last_provider_error`).
    """
    return last_provider_error("editor")


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
    #
    # Сразу помечаем пост 'editing': живой поллинг UI показывает на карточке
    # состояние «ИИ редактор…» — видно, какой пост обрабатывается прямо сейчас.
    set_post_editor_status(post_id, "editing")
    result = _edit_result(original)
    if result is None or not result.ok:
        set_post_editor_status(post_id, "none")
        if result is not None and result.aborted:
            # Прервано пользователем (выключен переключатель) — сигнал к
            # немедленной остановке всей пакетной обработки.
            logger.info("Редактура поста %s прервана пользователем", post_id)
            return {"post_id": post_id, "ok": False, "aborted": True}
        detail = last_editor_error() or "нет соединения"
        logger.warning(
            "Модель редактора недоступна (пост %s): %s", post_id, detail,
        )
        return {
            "post_id": post_id,
            "ok": False,
            "error": "модель недоступна",
            "detail": detail,
        }
    edited = result.content or ""
    saved = set_post_edited(post_id, edited)
    if saved:
        from ..db import set_post_editor_active
        set_post_editor_active(post_id, True)
    return {
        "post_id": post_id,
        "ok": bool(saved),
        "edited_len": len(edited),
        "changed": edited.strip() != original,
    }


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
    for i, p in enumerate(rows):
        # Кооперативная остановка: проверяем переключатель перед КАЖДЫМ
        # постом (чтение config.json дешево на фоне минутных вызовов модели) —
        # выключение должно останавливать пакет сразу, а не через 5 постов.
        if not load_config().schedule.editor_enabled:
            logger.info("ИИ-редактор выключен — прерывание пакетной обработки")
            break
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
        if res.get("aborted"):
            # Прервано пользователем (выключен переключатель) — стоп немедленно,
            # без дообработки остальных постов пачки.
            logger.info("Пакетная редактура прервана пользователем (пост %s)", pid)
            break
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
