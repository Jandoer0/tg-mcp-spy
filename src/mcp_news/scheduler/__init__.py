"""Фоновый планировщик обновления ленты и запуска ИИ-агента."""
from __future__ import annotations

from .worker import run_forever, start_scheduler

__all__ = ["start_scheduler", "run_forever"]
