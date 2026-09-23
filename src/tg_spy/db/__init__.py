"""Публичный API слоя БД.

Удобно импортировать всё отсюда: ``from tg_spy.db import add_source, ...``.
"""
from __future__ import annotations

from .connection import (
    DB_PATH,
    MAX_DB_BYTES,
    get_conn,
    init_db,
    rotate_if_needed,
    run_migrations,
)
from .repositories import posts, sources, topics

# Алиасы сущностей для удобного импорта верхнего уровня.
add_source = sources.add_source
remove_source = sources.remove_source
list_sources = sources.list_sources
list_sources_with_id = sources.list_sources_with_id
get_source = sources.get_source
get_all_sources = sources.get_all_sources
add_channel = sources.add_channel
remove_channel = sources.remove_channel
list_channels = sources.list_channels
get_channel = sources.get_channel

save_posts = posts.save_posts
get_posts = posts.get_posts
get_posts_after = posts.get_posts_after
get_oldest_post_date = posts.get_oldest_post_date
get_posts_by_tag = posts.get_posts_by_tag

add_topic = topics.add_topic
get_topic = topics.get_topic
get_topic_by_id = topics.get_topic_by_id
list_topics = topics.list_topics
remove_topic = topics.remove_topic
set_topic_active = topics.set_topic_active
update_topic_run = topics.update_topic_run
tag_post = topics.tag_post
untag_post = topics.untag_post
exclude_post = topics.exclude_post
get_excluded_ids = topics.get_excluded_ids
reset_exclusions = topics.reset_exclusions
get_tagged_posts = topics.get_tagged_posts
get_tagged_total = topics.get_tagged_total

__all__ = [
    "DB_PATH", "MAX_DB_BYTES", "get_conn", "init_db", "rotate_if_needed",
    "run_migrations",
    "add_source", "remove_source", "list_sources", "list_sources_with_id",
    "get_source", "get_all_sources", "add_channel", "remove_channel",
    "list_channels", "get_channel",
    "save_posts", "get_posts", "get_posts_after", "get_oldest_post_date",
    "get_posts_by_tag",
    "add_topic", "get_topic", "get_topic_by_id", "list_topics", "remove_topic",
    "set_topic_active", "update_topic_run", "tag_post", "untag_post",
    "exclude_post", "get_excluded_ids", "reset_exclusions", "get_tagged_posts",
    "get_tagged_total",
    "posts", "sources", "topics",
]
