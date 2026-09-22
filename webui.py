"""Веб-интерфейс для управления подписками.

Работает внутри того же ASGI-приложения, что и MCP-сервер (маршруты
добавляются через ``mcp.custom_route``), поэтому отдельный порт не нужен.
Страница доступна по адресу /ui, API — по /api/*.
"""
from pathlib import Path
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from db import (
    add_source,
    remove_source,
    list_sources,
    list_sources_with_id,
    get_source,
    get_posts,
)
from rss_parser import rsshub_telegram_url, DEFAULT_RSSHUB

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
    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))

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
                    {"date": p["date"], "text": p["text"], "url": p["url"]}
                    for p in rows
                ],
            }
        )

    # Без source — последние посты по всем подпискам (главный экран)
    rows = get_posts([s["id"] for s in list_sources()], "1970-01-01")[:limit]
    return JSONResponse(
        {
            "global": True,
            "posts": [
                {
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


async def api_refresh_posts(request: Request) -> JSONResponse:
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
        sources = (
            list_sources_with_id(only_kind)
            if only_kind
            else list_sources_with_id()
        )
        if not sources:
            return JSONResponse({"ok": True, "fetched": 0})

        ok, failed = 0, 0
        for src in sources:
            try:
                await _fetch(src)
            except Exception:
                failed += 1
                continue
            ok += 1
        return JSONResponse({"ok": True, "fetched": ok, "failed": failed})
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
    mcp.custom_route("/api/sources/{name:path}", methods=["DELETE"])(api_source)
    mcp.custom_route("/api/posts", methods=["GET"])(api_posts)
    mcp.custom_route("/api/refresh/posts", methods=["POST"])(api_refresh_posts)
    mcp.custom_route("/api/rsshub", methods=["GET"])(api_rsshub)
