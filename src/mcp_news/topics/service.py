"""Сервис «Мои темы»: высокоуровневые операции над темами.

Единая точка, которую вызывают и веб-маршруты, и MCP-инструменты, чтобы
не дублировать логику (создание/удаление/запуск агента/хронология).
"""
from __future__ import annotations

from typing import Optional

from ..db import (
    add_topic,
    exclude_post,
    get_tagged_total,
    get_topic,
    list_topics,
    remove_topic,
    reset_exclusions,
    set_topic_active,
    tag_post,
)
from . import agent
from .engine import get_chronology


def create_topic(
    name: str,
    tag: str,
    schedule_minutes: int = 1440,
    description: str = "",
) -> dict:
    """Создать тему и сразу запустить агента по имеющимся постам."""
    res = add_topic(name, tag, schedule_minutes, description=description)
    if res.get("ok"):
        agent.run_topic_agent_async(topic_id=res["id"])
    return res


def delete_topic(name: str) -> bool:
    return remove_topic(name)


def set_active(name: str, active: bool) -> bool:
    return set_topic_active(name, active)


def reset_exclusions(name: str, post_id: Optional[int] = None) -> int:
    topic = get_topic(name)
    if not topic:
        return 0
    return reset_exclusions(topic["id"], post_id)


def add_post_manual(name: str, post_id: int) -> Optional[dict]:
    """Ручное добавление поста из ленты в тему (mode='manual')."""
    topic = get_topic(name)
    if not topic:
        return None
    return tag_post(topic["id"], int(post_id), mode="manual")


def remove_post(name: str, post_id: int) -> bool:
    """Ручное удаление поста из темы + признак исключения."""
    topic = get_topic(name)
    if not topic:
        return False
    return exclude_post(topic["id"], int(post_id))


def get_topic_detail(name: str, limit: int = 200) -> Optional[dict]:
    topic = get_topic(name)
    if not topic:
        return None
    posts = get_chronology(topic["id"], limit=limit)
    total = get_tagged_total(topic["id"])
    return {"topic": topic, "total": total, "posts": posts}


def run_agent(name: str, max_batches: Optional[int] = None) -> dict:
    topic = get_topic(name)
    if not topic:
        return {"error": "тема не найдена"}
    if max_batches is not None:
        return agent.run_topic_agent(topic_id=topic["id"], max_batches=max_batches)
    return agent.run_topic_agent(topic_id=topic["id"])


def run_agent_async(name: str) -> None:
    topic = get_topic(name)
    if topic:
        agent.run_topic_agent_async(topic_id=topic["id"])


def run_all_agents() -> int:
    """Запустить агента для всех активных тем. Возвращает число запущенных."""
    count = 0
    for t in list_topics():
        if t.get("active"):
            agent.run_topic_agent_async(topic_id=t["id"])
            count += 1
    return count
