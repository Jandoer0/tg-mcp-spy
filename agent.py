"""Локальный ИИ-агент для отбора постов в «Мои темы».

Использует слабую локальную модель через OpenAI-совместимый эндпоинт
(по умолчанию Ollama). Задача модели — по теме (тегу) отобрать из общей
ленты посты, относящиеся к теме, и «скопировать» их в хронологию темы.
Без аналитики: модель только помечает релевантные посты (mode='tag'),
«движок» сайта сам собирает отобранные посты в отслеживаемую тему.
"""
import json
import logging
import os
import re
import threading
import time

import httpx

from config import load_config, get_provider
from db import (
    get_topic,
    get_topic_by_id,
    get_posts_after,
    get_excluded_ids,
    tag_post,
    update_topic_run,
    get_tagged_total,
)

logger = logging.getLogger(__name__)

# Сколько постов за один вызов модели. Меньше — короче запрос и меньше шанс
# вылететь по таймауту на слабой модели (для Qwen3:9b большой пакет >120с).
AGENT_BATCH = int(os.environ.get("AGENT_BATCH", "30"))
# Максимальная длина текста поста, передаваемая модели.
# Ограничено, чтобы пакет постов влезал в контекст модели (у базовой
# ornith-1.5:9b всего 4096 токенов — отсюда 400 символов на пост).
POST_EXCERPT_CHARS = int(os.environ.get("AGENT_EXCERPT_CHARS", "400"))
# Максимальная длина описания темы в промпте (чтобы не раздувать контекст).
TAG_DESCRIPTION_CHARS = int(os.environ.get("AGENT_DESCRIPTION_CHARS", "280"))
# Сколько пачек обработать за один прогон (защита от слишком долгой работы).
AGENT_MAX_BATCHES = int(os.environ.get("AGENT_MAX_BATCHES", "20"))
# Число повторных попыток обращения к (слабой) модели при сбоях сети/таймаутах.
AGENT_RETRIES = int(os.environ.get("AGENT_RETRIES", "2"))
# Пауза между попытками (сек), растёт линейно (1x, 2x, ...).
AGENT_RETRY_BACKOFF = float(os.environ.get("AGENT_RETRY_BACKOFF", "1.5"))
# Таймаут одного запроса к модели (сек) — чтобы Ollama не блокировал интерфейс.
# Для рассуждающих/слабых моделей на больших пакетах стоит больше.
AGENT_REQUEST_TIMEOUT = float(os.environ.get("AGENT_REQUEST_TIMEOUT", "300.0"))


def _chat(messages: list[dict], temperature: float = 0.0) -> str | None:
    """Один вызов OpenAI-совместимого chat/completions. Возвращает текст ответа."""
    cfg = load_config()
    prov = get_provider(cfg)
    base = (prov.get("baseUrl") or "http://127.0.0.1:11434/v1").rstrip("/")
    url = f"{base}/chat/completions"
    model = cfg.get("model") or "llama3.2"
    api_key = prov.get("apiKey") or "ollama"
    compat = prov.get("compat") or {}

    # Роль системного сообщения: слабые модели/прокси не всегда поддерживают
    # developer-роль — по умолчанию используем system.
    sys_role = "developer" if compat.get("supportsDeveloperRole") else "system"
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
        # Явно нестриминговый ответ — иначе httpx может ждать тела потока.
        "stream": False,
    }
    # Отключить рассуждения (CoT) для моделей вроде Qwen3 — иначе они
    # «думают» десятки секунд даже на простом фильтре и не укладываются
    # в таймаут. Параметр специфичен для Ollama.
    if compat.get("disableThinking"):
        payload["think"] = False
    # Ollama умеет форсировать JSON-ответ через format (для надёжности).
    if compat.get("jsonObjectFormat"):
        payload["format"] = {"type": "json_object"}

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Повторные попытки: слабая локальная модель или Ollama могут
    # зависать/падать — не блокируем интерфейс, пробуем ещё раз с паузой.
    attempts = max(0, AGENT_RETRIES) + 1
    last_err: Exception | None = None
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
    logger.error(
        "Модель недоступна после %d попыток (%s): %s", attempts, url, last_err
    )
    return None


def _extract_json(text: str) -> dict | None:
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
    # Описание помогает модели не отбирать всё подряд: например, тег
    # «Мобилизация» + описание «ресурсы организма человека» → только про здоровье.
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
        f"(прямо упоминается или речь идёт об этом "
        f"же предмете/событии/теме).\n\n"
        f"Верни ТОЛЬКО JSON строго в формате:\n"
        f'{{"matches": [список номеров постов, которые относятся к теме]}}\n'
        f'Если ни один не подходит — верни {{"matches": []}}.\n'
        f"Не добавляй аналитику, комментарии и текст вне JSON.\n\n"
        f"Посты:\n" + "\n".join(lines)
    )
    return [
        {"role": "system", "content": cfg.get("systemPrompt", "")},
        {"role": "user", "content": user},
    ]


def match_topic_posts(topic: dict, posts: list[dict], content: str | None = None) -> list[int]:
    """Вернуть 1-based индексы постов, относящихся к теме.

    content — уже полученный от модели ответ (чтобы не дёргать модель
    повторно). Если None — дёрнуть модель самостоятельно.
    """
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
    topic: dict | None = None,
    topic_id: int | None = None,
    topic_name: str | None = None,
    max_batches: int = AGENT_MAX_BATCHES,
) -> dict:
    """Один прогон агента для темы.

    Сканирует новые посты (id > last_post_id) пачками, просит модель
    отметить релевантные и копирует их в хронологию темы (mode='tag').
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
        # Один вызов модели на пачку. При таймауте/ошибке content будет None.
        try:
            content = _chat(_build_messages(topic, candidates))
        except Exception as e:
            error = str(e)
            logger.error("Ошибка модели для темы %s: %s", topic.get("name"), e)
            content = None
        if content is None:
            # Нет ответа модели — НЕ сдвигаем high-water mark, чтобы эту пачку
            # можно было повторить в следующем прогоне (иначе посты потеряются).
            logger.warning(
                "Агент по теме %s: нет ответа модели, пачка пропущена (повтор при следующем запуске)",
                topic.get("name"),
            )
            break
        matched_idx = match_topic_posts(topic, candidates, content)
        # Пропускаем посты, которые пользователь вручно исключил из темы:
        # агент не должен возвращать их обратно без явного сброса.
        excluded = get_excluded_ids(topic["id"], [p["id"] for p in candidates])
        # Модель *присваивает тег* релевантным постам (mode='ai'); само
        # копирование в хронологию темы выполняет «движок» (get_tagged_posts).
        for idx in matched_idx:
            post = candidates[idx - 1]
            if post["id"] in excluded:
                continue
            row = tag_post(topic["id"], post["id"], mode="ai")
            if row:
                added_total += 1
        # продвигаем high-water mark до максимального id из пачки
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


def run_topic_agent_async(topic_id: int | None = None, topic_name: str | None = None):
    """Запустить прогон агента в фоновом потоке (не блокирует ответ HTTP)."""

    def _t():
        try:
            run_topic_agent(topic_id=topic_id, topic_name=topic_name)
        except Exception as e:
            logger.error("Фоновый прогон агента упал: %s", e)

    threading.Thread(target=_t, name="topic-agent", daemon=True).start()


def test_connection() -> dict:
    """Проверить связь с провайдером/моделью (для кнопки «Проверить соединение»).

    Делает один минимальный запрос к модели и возвращает {"ok", "reply"} или
    {"ok": False, "error"}. Не меняет данные.
    """
    cfg = load_config()
    model = cfg.get("model") or "llama3.2"
    try:
        content = _chat(
            [
                {"role": "system", "content": cfg.get("systemPrompt", "")},
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
        return {"ok": True, "model": model, "reply": (content or "").strip()[:200]}
    except Exception as e:  # если _chat не перехватил
        return {"ok": False, "model": model, "error": str(e)}
