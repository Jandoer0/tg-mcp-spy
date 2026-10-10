"""Веб-транспорт: сборка приложения (MCP + веб/API)."""
from __future__ import annotations

from .app import create_app, register_web

__all__ = ["create_app", "register_web"]
