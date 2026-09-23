"""tg-mcp-spy — агрегатор Telegram/RSS-лент с локальным ИИ-агентом.

Архитектура: доменное ядро (db / ingest / topics) + адаптеры
(веб-API на FastAPI, MCP-сервер) + фоновый воркер (scheduler).
"""
from __future__ import annotations

__version__ = "0.3.0"

__all__ = ["__version__"]
