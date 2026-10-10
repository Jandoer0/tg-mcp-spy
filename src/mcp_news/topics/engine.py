"""«Движок» тем: сбор хронологии темы из отобранных постов.

По замыслу модель только *назначает теги* постам (mode='ai'/'manual'),
а «движок» сайта сам собирает посты с нужным тегом в хронологию темы.
Здесь — тонкая надстройка над репозиториями для этой «сборки».
"""
from __future__ import annotations

from ..db import get_posts_by_tag, get_tagged_posts, get_tagged_total


def get_chronology(topic_id: int, offset: int = 0, limit: int = 200) -> list[dict]:
    """Посты хронологии темы (отобранные агентом или вручную)."""
    return get_tagged_posts(topic_id, offset=offset, limit=limit)


def get_chronology_total(topic_id: int) -> int:
    return get_tagged_total(topic_id)


def global_by_tag(tag: str, limit: int = 300) -> list[dict]:
    """Посты общей ленты, отмеченные тегом выбранной темы (фильтр в ленте)."""
    return get_posts_by_tag(tag, limit)
