"""Командный интерфейс tg-spy: serve | worker | migrate.

Позволяет запускать веб+API+MCP и фоновый воркер независимо (например,
воркер — отдельным контейнером, чтобы тяжёлый прогон агента не влиял
на отзывчивость UI).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("tg-spy")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api.app import create_app

    host = args.host or _env("HOST", "0.0.0.0")
    port = args.port or int(_env("PORT", "8000"))

    if args.reload:
        # В режиме перезагрузки — фабрика (пересоздаётся воркером).
        uvicorn.run(
            "tg_spy.api.app:create_app", host=host, port=port,
            reload=True, factory=True,
        )
    else:
        app = create_app()
        uvicorn.run(app, host=host, port=port)
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    from .scheduler.worker import run_forever

    logger.info("Запуск воркера (планировщик + агент)")
    run_forever()
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from .db import init_db

    init_db()
    logger.info("Миграции применены")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tg-spy", description="tg-mcp-spy сервер")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("serve", help="веб-интерфейс + API + MCP на одном порту")
    sp.add_argument("--host", default=None)
    sp.add_argument("--port", type=int, default=None)
    sp.add_argument("--reload", action="store_true", help="перезагрузка кода (dev)")
    sp.set_defaults(func=cmd_serve)

    wp = sub.add_parser("worker", help="только фоновый планировщик + агент")
    wp.set_defaults(func=cmd_worker)

    mp = sub.add_parser("migrate", help="применить миграции БД")
    mp.set_defaults(func=cmd_migrate)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
