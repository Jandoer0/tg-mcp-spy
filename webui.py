"""Веб-интерфейс для управления подписками.

Работает внутри того же ASGI-приложения, что и MCP-сервер (маршруты
добавляются через ``mcp.custom_route``), поэтому отдельный порт не нужен.
Страница доступна по адресу /ui, API — по /api/*.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from db import (
    add_source,
    list_sources,
    list_sources_with_id,
    get_source,
    get_posts,
    get_oldest_post_date,
    save_posts,
)
from tg_parser import fetch_page, parse_posts
from rss_parser import fetch_feed, parse_feed, rsshub_telegram_url, DEFAULT_RSSHUB

UI_DIR = Path(__file__).parent / "ui"


# --------------------------------------------------------------------------- #
# Обработчики (все async — требование mcp.custom_route)
# --------------------------------------------------------------------------- #
def _sources_view():
    return [
        {
            "id": s["id"],
            "kind": s["kind"],
            "name": s["name"],
            "url": s["url"],
            "added_at": s["added_at"],
        }
        for s in list_sources()
    ]


async def ui_index(request: Request) -> HTMLResponse:
    return HTMLResponse((UI_DIR / "index.html").read_text(encoding="utf-8"))


async def api_sources(request: Request) -> JSONResponse:
    if request.method == "GET":
        return JSONResponse(_sources_view())

    # POST — добавить подписку
    data = await request.json()
    kind = data.get("kind")
    name = (data.get("name") or "").strip()
    url = (data.get("url") or "").strip() or None

    if not name:
        return JSONResponse({"error": "Укажите name"}, status_code=400)
    if kind not in ("telegram", "rss"):
        return JSONResponse({"error": "kind должен быть telegram или rss"}, status_code=400)
    if kind == "rss" and not url:
        return JSONResponse({"error": "Для rss нужно указать url"}, status_code=400)

    src = add_source(kind, name, url)
    return JSONResponse({"ok": True, "source": src}, status_code=201)


async def api_posts(request: Request) -> JSONResponse:
    name = request.query_params.get("source", "").strip().lower().lstrip("@")
    kind = request.query_params.get("kind", "").strip().lower()
    if kind not in ("telegram", "rss"):
        kind = ""
    try:
        limit = int(request.query_params.get("limit", "300"))
    except ValueError:
        limit = 300
    limit = max(1, min(limit, 1000))

    if name:
        # Посты конкретной подписки
        src = get_source(name)
        if not src:
            return JSONResponse({"error": "Подписка не найдена"}, status_code=404)
        rows = get_posts([src["id"]], "1970-01-01")[:limit]
        return JSONResponse(
            {
                "source": name,
                "kind": src["kind"],
                "global": False,
                "posts": [
                    {"id": p["id"], "date": p["date"], "text": p["text"], "url": p["url"]}
                    for p in rows
                ],
            }
        )

    # Без source — лента по всем подпискам (главный экран).
    # Опционально фильтруем по типу источника (telegram/rss), чтобы
    # показывать «несколько дней» накопленных постов из кеша.
    srcs = list_sources(kind) if kind else list_sources()
    rows = get_posts([s["id"] for s in srcs], "1970-01-01")[:limit]
    return JSONResponse(
        {
            "global": True,
            "kind": kind,
            "posts": [
                {
                    "id": p["id"],
                    "date": p["date"],
                    "text": p["text"],
                    "url": p["url"],
                    "source": p["source"],
                    "kind": p["kind"],
                }
                for p in rows
            ],
        }
    )


# --------------------------------------------------------------------------- #
# Пересборка постов из источников (Telegram t.me/s или RSS/RSSHub)
# --------------------------------------------------------------------------- #
def _refresh_telegram(source: dict, cutoff: str) -> None:
    """Подтянуть свежие посты Telegram-канала до даты ``cutoff`` (включительно)."""
    channelname = source["name"]
    before = None
    for _ in range(10):
        if before is not None:
            oldest = get_oldest_post_date(source["id"])
            if oldest and oldest < cutoff:
                break
        try:
            html = fetch_page(channelname, before)
        except Exception:
            break
        posts = parse_posts(html)
        if not posts:
            break
        save_posts(source["id"], posts)
        if posts[-1]["date"] and posts[-1]["date"] < cutoff:
            break
        before = posts[-1]["ext_id"]


def _refresh_rss(source: dict) -> None:
    """Подтянуть посты из RSS/RSSHub-ленты источника."""
    try:
        content = fetch_feed(source["url"])
    except Exception:
        return
    posts = parse_feed(content)
    save_posts(source["id"], posts)


async def api_refresh_posts(request: Request) -> JSONResponse:
    """POST /api/refresh/posts — подтянуть свежие посты за последние N суток.

    Тело: {"days": 1, "kind": ""|"telegram"|"rss"}. По умолчанию days=1 (сутки).
    """
    async def _fetch(source: dict) -> None:
        if source["kind"] == "telegram":
            _refresh_telegram(source, cut_off_str)
        else:
            _refresh_rss(source)

    try:
        if request.method != "POST":
            return JSONResponse({"error": "Метод не поддерживается"}, status_code=405)
        data = await request.json()
        only_kind = (data.get("kind") or "").strip()
        try:
            days = int(data.get("days", 1))
        except (TypeError, ValueError):
            days = 1
        days = max(1, min(days, 30))
        cut_off_str = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%d"
        )
        sources = (
            list_sources_with_id(only_kind)
            if only_kind
            else list_sources_with_id()
        )
        if not sources:
            return JSONResponse(
                {"ok": True, "fetched": 0, "failed": 0, "message": "Нет подписок для обновления"}
            )

        ok, failed = 0, 0
        for src in sources:
            try:
                await _fetch(src)
            except Exception:
                failed += 1
                continue
            ok += 1
        return JSONResponse(
            {"ok": True, "fetched": ok, "failed": failed, "days": days, "cutoff": cut_off_str}
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_rsshub(request: Request) -> JSONResponse:
    username = request.query_params.get("username", "").strip()
    base = request.query_params.get("base", "").strip() or DEFAULT_RSSHUB
    if not username:
        return JSONResponse({"error": "Укажите ?username=..."}, status_code=400)
    return JSONResponse({"url": rsshub_telegram_url(base, username)})


def register_ui(mcp):
    """Зарегистрировать маршруты веб-интерфейса на MCP-сервере."""
    mcp.custom_route("/", methods=["GET"])(lambda request: RedirectResponse("/ui"))
    mcp.custom_route("/ui", methods=["GET"])(ui_index)
    mcp.custom_route("/api/sources", methods=["GET", "POST"])(api_sources)
    mcp.custom_route("/api/posts", methods=["GET"])(api_posts)
    mcp.custom_route("/api/refresh/posts", methods=["POST"])(api_refresh_posts)
    mcp.custom_route("/api/rsshub", methods=["GET"])(api_rsshub)
