"""Точка входа уровня репозитория.

Запуск: ``python main.py`` (равносильно ``python -m mcp_news serve``).
Вся логика — в пакете ``mcp_news``; здесь только делегирование.
"""
import sys

from mcp_news.cli import main

if __name__ == "__main__":
    sys.exit(main())
