"""Сборка приложения.

MCP-сервер — корневое ASGI-приложение: ``mcp.streamable_http_app``
отдаёт протокол MCP на /mcp, а веб-маршруты и статика добавляются
через ``mcp.custom_route`` (проверенный паттерн, без проблем с монтированием
и lifespan). Всё на одном порту, но слои разделены.
"""
from __future__ import annotations

import logging

from ..db import init_db, rotate_if_needed
from ..mcp import mcp
from ..scheduler.worker import start_scheduler
from .web import (
    api_config,
    api_config_models,
    api_config_test,
    api_posts,
    api_posts_tags,
    api_posts_editor,
    api_editor_run,
    api_editor_post,
    api_rsshub,
    api_refresh_posts,
    api_source_delete,
    api_sources,
    api_topics,
    api_topics_posts,
    api_topics_reset,
    api_topics_run,
    api_topics_run_all,
    api_topics_toggle,
    root_redirect,
    static_handler,
    ui_index,
)

logger = logging.getLogger(__name__)


def register_web(mcp) -> None:
    """Зарегистрировать веб-маршруты и статику на MCP-сервере."""
    mcp.custom_route("/", methods=["GET"])(root_redirect)
    mcp.custom_route("/ui", methods=["GET"])(ui_index)
    mcp.custom_route("/static/{path:path}", methods=["GET"])(static_handler)

    mcp.custom_route("/api/sources", methods=["GET", "POST"])(api_sources)
    mcp.custom_route("/api/sources/{name}", methods=["DELETE"])(api_source_delete)
    mcp.custom_route("/api/posts", methods=["GET"])(api_posts)
    mcp.custom_route("/api/posts/tags", methods=["GET"])(api_posts_tags)
    mcp.custom_route("/api/posts/editor", methods=["GET"])(api_posts_editor)
    mcp.custom_route("/api/editor/run", methods=["POST"])(api_editor_run)
    mcp.custom_route("/api/editor/post/active", methods=["POST"])(api_editor_post)
    mcp.custom_route("/api/editor/post", methods=["POST", "DELETE"])(api_editor_post)
    mcp.custom_route("/api/refresh/posts", methods=["POST"])(api_refresh_posts)
    mcp.custom_route("/api/rsshub", methods=["GET"])(api_rsshub)

    mcp.custom_route("/api/topics", methods=["GET", "POST", "DELETE"])(api_topics)
    mcp.custom_route("/api/topics/posts", methods=["GET", "POST", "DELETE"])(
        api_topics_posts
    )
    mcp.custom_route("/api/topics/run", methods=["POST"])(api_topics_run)
    mcp.custom_route("/api/topics/run-all", methods=["POST"])(api_topics_run_all)
    mcp.custom_route("/api/topics/toggle", methods=["POST"])(api_topics_toggle)
    mcp.custom_route("/api/topics/reset", methods=["POST"])(api_topics_reset)

    mcp.custom_route("/api/config", methods=["GET", "POST"])(api_config)
    mcp.custom_route("/api/config/test", methods=["POST"])(api_config_test)
    mcp.custom_route("/api/config/models", methods=["POST"])(api_config_models)


def create_app(start_background: bool = True):
    """Собрать ASGI-приложение (MCP на /mcp + веб/API на /, /ui, /api, /static)."""
    # Подчистить базу при старте, если она уже превышает лимит размера.
    init_db()
    rotate_if_needed()

    register_web(mcp)

    # Фоновый планировщик: авто-обновление ленты + периодический запуск агента.
    if start_background:
        start_scheduler()

    return mcp.streamable_http_app(json_response=True)
