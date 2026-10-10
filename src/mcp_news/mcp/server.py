"""MCP-сервер как адаптер к доменному ядру.

Создаёт экземпляр ``MCPServer`` и регистрирует инструменты/ресурсы/промпты
(тонкие обёртки над слоями db / ingest / topics). Само ASGI-приложение
собирается функцией :func:`create_mcp_app` и монтируется в FastAPI.
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

# Единый экземпляр сервера. Инструменты/ресурсы/промпты регистрируются
# декораторами при импорте подмодулей ниже.
mcp = MCPServer("Telegram Watcher")

# Импортируем подмодули, чтобы сработали декораторы регистрации.
from . import prompts, resources, tools  # noqa: E402,F401


def create_mcp_app():
    """Вернуть Starlette-приложение MCP для монтирования в FastAPI.

    ``streamable_http_path="/"`` — чтобы при монтировании по префиксу
    ``/mcp`` эндпоинт отвечал ровно на ``/mcp``.
    """
    return mcp.streamable_http_app(streamable_http_path="/", json_response=True)
