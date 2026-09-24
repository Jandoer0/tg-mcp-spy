"""Локальный ИИ-агент для отбора постов в «Мои темы».

Использует слабую локальную модель через OpenAI-совместимый эндпоинт
(по умолчанию Ollama). Задача модели — по теме (тегу) отобрать из общей
ленты посты, относящиеся к теме, и «скопировать» их в хронологию темы.
Без аналитики: модель только помечает релевантные посты (mode='ai'),
«движок» сайта сам собирает отобранные посты в отслеживаемую тему.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Optional

import httpx

from ..config import get_provider, load_config
from ..db import (
    get_excluded_ids,
    get_posts_after,
    get_tagged_total,
    get_topic,
    get_topic_by_id,
    tag_post,
    update_topic_run,
)

logger = logging.getLogger(__name__)

# Сколько постов за один вызов модели.
AGENT_BATCH = int(os.environ.get("AGENT_BATCH", "10"))
# Максимальная длина текста поста, передаваемая модели.
POST_EXCERPT_CHARS = int(os.environ.get("AGENT_EXCERPT_CHARS", "400"))
# Максимальная длина описания темы в промпте.
TAG_DESCRIPTION_CHARS = int(os.environ.get("AGENT_DESCRIPTION_CHARS", "280"))
# Сколько пачек обработать за один прогон.
AGENT_MAX_BATCHES = int(os.environ.get("AGENT_MAX_BATCHES", "20"))
# Число повторных попыток обращения к модели при сбоях.
AGENT_RETRIES = int(os.environ.get("AGENT_RETRIES", "2"))
# Пауза между попытками (сек), растёт линейно.
AGENT_RETRY_BACKOFF = float(os.environ.get("AGENT_RETRY_BACKOFF", "1.5"))
# Таймаут одного запроса к модели (сек).
AGENT_REQUEST_TIMEOUT = float(os.environ.get("AGENT_REQUEST_TIMEOUT", "300.0"))


def _chat(messages: list[dict], temperature: float = 0.0) -> Optional[str]:
    """Один вызов OpenAI-совместимого chat/completions. Возвращает текст."""
    cfg = load_config()
    prov = get_provider(cfg)
    base = (prov.base_url or "http://127.0.0.1:11434/v1").rstrip("/")
    url = f"{base}/chat/completions"
    model = cfg.model or "llama3.2"
    api_key = prov.api_key or "ollama"
    compat = prov.compat

    sys_role = "developer" if compat.supports_developer_role else "system"
    msgs = []
    for m in messages:
        if m.get("role") == "system":
            msgs.append({"role": sys_role, "content": m["content"]})
        else:
            msgs.append(m)

    payload = {
        "model": model,
        "messages": msgs,
        "temperature": temperature,
        "stream": False,
    }
    if compat.disable_thinking:
        payload["think"] = False
    if compat.json_object_format:
        payload["format"] = {"type": "json_object"}

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    attempts = max(0, AGENT_RETRIES) + 1
    last_err: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            resp = httpx.post(
                url, headers=headers, json=payload, timeout=AGENT_REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # таймаут, сетевая ошибка, не-JSON, 5xx
            last_err = e
            logger.warning(
                "Ошибка обращения к модели (попытка %d/%d, %s): %s",
                attempt + 1, attempts, url, e,
            )
            if attempt < attempts - 1:
                time.sleep(AGENT_RETRY_BACKOFF * (attempt + 1))
    logger.error("Модель недоступна после %d попыток (%s): %s", attempts, url, last_err)
    return None


def _extract_json(text: str) -> Optional[dict]:
    """Извлечь JSON-объект из ответа модели (с учётом markdown-обёрток)."""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.IGNORECASE)
    if m:
        t = m.group(1).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    try:
        obj = json.loads(t)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _build_messages(topic: dict, posts: list[dict]) -> list[dict]:
    cfg = load_config()
    tag = (topic.get("tag") or topic.get("name") or "").strip()
    description = (topic.get("description") or "").strip()[:TAG_DESCRIPTION_CHARS]
    lines = []
    for i, p in enumerate(posts, start=1):
        text = (p.get("text") or "").strip().replace("\n", " ")
        if len(text) > POST_EXCERPT_CHARS:
            text = text[:POST_EXCERPT_CHARS] + "…"
        lines.append(f"{i}. [{p.get('date', '')}] {p.get('source', '')}: {text}")
    desc_block = ""
    if description:
        desc_block = (
            f"ЧТО ИМЕННО ИМЕЕТ В ВИДУ ПОЛЬЗОВАТЕЛЬ (описание темы): {description}\n\n"
            f"Отбирай ТОЛЬКО посты, которые соответствуют ЭТОМУ описанию — даже если "
            f"слово-тег встречается в другом, неподходящем смысле, такие посты НЕ отбирай.\n\n"
        )
    user = (
        f"ТЕМА (тег): {tag}\n\n"
        f"{desc_block}"
        f"Ниже посты из общей новостной ленты. Для каждого поста определи, "
        f"относится ли он к теме «{tag}» с учётом описания выше "
        f"(прямо упоминается или речь идёт об этом же предмете/событии/теме).\n\n"
        f"ВАЖНО: выведи ТОЛЬКО одну строку — JSON-объект, без какого-либо "
        f"другого текста, без рассуждений и без markdown. Никаких пояснений. "
        f"Только JSON строго в формате:\n"
        f'{{"matches": [список номеров постов, которые относятся к теме]}}\n'
        f'Если ни один не подходит — верни {{"matches": []}}.\n\n'
        f"Пример правильного ответа (если подходят посты 1 и 3):\n"
        f'{{"matches": [1, 3]}}\n\n'
        f"Посты:\n" + "\n".join(lines)
    )
    return [
        {"role": "system", "content": cfg.system_prompt},
        {"role": "user", "content": user},
    ]


def match_topic_posts(
    topic: dict, posts: list[dict], content: Optional[str] = None
) -> list[int]:
    """Вернуть 1-based индексы постов, относящихся к теме."""
    if not posts:
        return []
    if content is None:
        content = _chat(_build_messages(topic, posts))
    obj = _extract_json(content)
    if not obj:
        return []
    matches = obj.get("matches")
    if not isinstance(matches, list):
        return []
    result = []
    seen = set()
    for x in matches:
        try:
            idx = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= len(posts) and idx not in seen:
            seen.add(idx)
            result.append(idx)
    return result


def run_topic_agent(
    topic: Optional[dict] = None,
    topic_id: Optional[int] = None,
    topic_name: Optional[str] = None,
    max_batches: int = AGENT_MAX_BATCHES,
) -> dict:
    """Один прогон агента для темы.

    Сканирует новые посты (id > last_post_id) пачками, просит модель
    отметить релевантные и копирует их в хронологию темы (mode='ai').
    Возвращает сводку: {"topic", "scanned", "added", "total", "error"}.
    """
    if topic is None:
        if topic_id is not None:
            topic = get_topic_by_id(topic_id)
        elif topic_name is not None:
            topic = get_topic(topic_name)
        else:
            return {"error": "тема не указана"}
    if not topic:
        return {"error": "тема не найдена"}

    last_post_id = topic.get("last_post_id") or 0
    scanned_total = 0
    added_total = 0
    error = None
    batches = 0

    while batches < max_batches:
        candidates = get_posts_after(last_post_id, AGENT_BATCH)
        if not candidates:
            break
        scanned_total += len(candidates)
        try:
            content = _chat(_build_messages(topic, candidates))
        except Exception as e:
            error = str(e)
            logger.error("Ошибка модели для темы %s: %s", topic.get("name"), e)
            content = None
        if content is None:
            # Нет ответа модели — НЕ сдвигаем high-water mark, чтобы эту
            # пачку можно было повторить в следующем прогоне.
            logger.warning(
                "Агент по теме %s: нет ответа модели, пачка пропущена (повтор при следующем запуске)",
                topic.get("name"),
            )
            break
        matched_idx = match_topic_posts(topic, candidates, content)
        excluded = get_excluded_ids(topic["id"], [p["id"] for p in candidates])
        for idx in matched_idx:
            post = candidates[idx - 1]
            if post["id"] in excluded:
                continue
            row = tag_post(topic["id"], post["id"], mode="ai")
            if row:
                added_total += 1
        last_post_id = max(p["id"] for p in candidates)
        update_topic_run(topic["id"], last_post_id=last_post_id)
        batches += 1

    total = get_tagged_total(topic["id"])
    return {
        "topic": topic.get("name"),
        "scanned": scanned_total,
        "added": added_total,
        "total": total,
        "error": error,
    }


def run_topic_agent_async(
    topic_id: Optional[int] = None, topic_name: Optional[str] = None
) -> None:
    """Запустить прогон агента в фоновом потоке (не блокирует ответ HTTP)."""

    def _t() -> None:
        try:
            run_topic_agent(topic_id=topic_id, topic_name=topic_name)
        except Exception as e:  # noqa: BLE001
            logger.error("Фоновый прогон агента упал: %s", e)

    threading.Thread(target=_t, name="topic-agent", daemon=True).start()


def _names_from_openai(data) -> list[str]:
    """Извлечь имена моделей из ответа OpenAI-совместимого /models."""
    out: list[str] = []
    items = data.get("data") if isinstance(data, dict) else data
    if isinstance(items, list):
        for m in items:
            if isinstance(m, dict):
                name = m.get("id") or m.get("name") or m.get("model")
                if name:
                    out.append(str(name))
    return out


def list_models(base_url: str, api_key: str) -> dict:
    """Запросить у провайдера список доступных моделей.

    Сначала пробуем OpenAI-совместимый /models, при неудаче или пустом
    ответе — нативный Ollama /api/tags (провайдер сам выбирает порт).
    Используется в настройках провайдера: сайт опрашивает провайдера и
    подставляет список моделей в поле выбора.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "error": "Не указан адрес провайдера (API URL)"}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    models: list[str] = []
    last_err = None

    # 1) OpenAI-совместимый эндпоинт /models.
    try:
        resp = httpx.get(f"{base}/models", headers=headers, timeout=15.0)
        if resp.status_code == 200:
            models = _names_from_openai(resp.json())
    except Exception as e:  # noqa: BLE001
        last_err = e

    # 2) Фолбэк на нативный Ollama /api/tags (если /models пуст или недоступен).
    if not models:
        try:
            root = base[:-3] if base.endswith("/v1") else base
            resp = httpx.get(f"{root}/api/tags", headers=headers, timeout=15.0)
            if resp.status_code == 200:
                models = [
                    str(m["name"])
                    for m in resp.json().get("models", [])
                    if isinstance(m, dict) and m.get("name")
                ]
        except Exception as e:  # noqa: BLE001
            if last_err is None:
                last_err = e

    models = sorted(set(filter(None, models)))
    if models:
        return {"ok": True, "models": models}
    return {"ok": False, "error": f"Не удалось получить список моделей: {last_err or 'пусто'}"}


def test_connection() -> dict:
    """Проверить связь с провайдером/моделью (для кнопки «Проверить соединение»)."""
    cfg = load_config()
    model = cfg.model or "llama3.2"
    try:
        content = _chat(
            [
                {"role": "system", "content": cfg.system_prompt},
                {
                    "role": "user",
                    "content": "Кратко подтверди, что ты на связи, одним-двумя словами.",
                },
            ],
            temperature=0.0,
        )
        if content is None:
            return {
                "ok": False,
                "model": model,
                "error": "Модель не вернула ответ (нет соединения / таймаут / ошибка провайдера)",
            }
        reply = (content or "").strip()[:200]
        # Читаемое сообщение для UI: «Связь установлена. Модель <имя> активна.»
        return {
            "ok": True,
            "model": model,
            "reply": reply,
            "message": f"Связь установлена. Модель {model} активна.",
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "model": model, "error": str(e)}
