"""Точка входа уровня репозитория.

Запуск: ``python main.py`` (равносильно ``python -m tg_spy serve``).
Вся логика — в пакете ``tg_spy``; здесь только делегирование.
"""
import sys

from tg_spy.cli import main

if __name__ == "__main__":
    sys.exit(main())
