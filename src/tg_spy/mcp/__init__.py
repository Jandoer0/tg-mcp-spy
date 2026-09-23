"""MCP-адаптер: сервер, инструменты, ресурсы, промпты."""
from __future__ import annotations

from .server import create_mcp_app, mcp

__all__ = ["mcp", "create_mcp_app"]
