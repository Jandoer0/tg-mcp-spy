"""Веб-интерфейс для управления подписками.

Работает внутри того же ASGI-приложения, что и MCP-сервер (маршруты
добавляются через ``mcp.custom_route``), поэтому отдельный порт не нужен.
Страница доступна по адресу /ui, API — по /api/*.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import load_config, get_provider, save_config, get_config_path

from db import (
    add_source,
    list_sources,
    list_sources_with_id,
    get_source,
    get_posts,
    get_oldest_post_date,
    save_posts,
    # «Мои темы»
    add_topic,
    get_topic,
    list_topics,
    remove_topic,
    tag_post,
    exclude_post,
    reset_exclusions,
    get_tagged_posts,
    get_tagged_total,
    get_posts_by_tag,
    set_topic_active,
)
from tg_parser import fetch_page, parse_posts
from rss_parser import fetch_feed, parse_feed, rsshub_telegram_url, DEFAULT_RSSHUB
from agent import run_topic_agent, run_topic_agent_async, test_connection

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
    tag = request.query_params.get("tag", "").strip()
    if kind not in ("telegram", "rss"):
        kind = ""
    try:
        limit = int(request.query_params.get("limit", "300"))
    except ValueError:
        limit = 300
    limit = max(1, min(limit, 1000))

    if tag:
        # Фильтр по тегу (выпадающее меню во вкладке «Лента новостей»):
        # только посты общей ленты, отмеченные тегом выбранной темы.
        rows = get_posts_by_tag(tag, limit)
        return JSONResponse(
            {
                "global": True,
                "tag": tag,
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


def refresh_all_sources(days: int = 1, kind: str = "") -> dict:
    """Подтянуть свежие посты по всем (или выбранного типа) источникам.

    Используется и из API-эндпоинта обновления, и из фонового планировщика.
    """
    cut_off_str = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%d"
    )
    sources = list_sources_with_id(kind) if kind else list_sources_with_id()
    ok, failed = 0, 0
    for src in sources:
        try:
            if src["kind"] == "telegram":
                _refresh_telegram(src, cut_off_str)
            else:
                _refresh_rss(src)
            ok += 1
        except Exception:
            failed += 1
    return {"fetched": ok, "failed": failed, "days": days, "cutoff": cut_off_str}


async def api_refresh_posts(request: Request) -> JSONResponse:
    """POST /api/refresh/posts — подтянуть свежие посты за последние N суток.

    Тело: {"days": 1, "kind": ""|"telegram"|"rss"}. По умолчанию days=1 (сутки).
    """
    if request.method != "POST":
        return JSONResponse({"error": "Метод не поддерживается"}, status_code=405)
    try:
        data = await request.json()
    except Exception:
        data = {}
    only_kind = (data.get("kind") or "").strip()
    try:
        days = int(data.get("days", 1))
    except (TypeError, ValueError):
        days = 1
    days = max(1, min(days, 30))
    try:
        result = refresh_all_sources(days=days, kind=only_kind)
        return JSONResponse({"ok": True, **result})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_rsshub(request: Request) -> JSONResponse:
    username = request.query_params.get("username", "").strip()
    base = request.query_params.get("base", "").strip() or DEFAULT_RSSHUB
    if not username:
        return JSONResponse({"error": "Укажите ?username=..."}, status_code=400)
    return JSONResponse({"url": rsshub_telegram_url(base, username)})


# --------------------------------------------------------------------------- #
# «Мои темы»: темы, их хронология и запуск локального ИИ-агента
# --------------------------------------------------------------------------- #
async def api_topics(request: Request) -> JSONResponse:
    method = request.method
    if method == "GET":
        return JSONResponse(list_topics())
    if method == "POST":
        data = await request.json()
        name = (data.get("name") or "").strip()
        tag = (data.get("tag") or "").strip()
        description = (data.get("description") or "").strip()
        schedule = data.get("schedule_minutes", 30)
        if not name or not tag:
            return JSONResponse({"error": "Укажите name и tag"}, status_code=400)
        res = add_topic(name, tag, schedule, description=description)
        if not res.get("ok"):
            return JSONResponse({"error": res.get("error")}, status_code=400)
        # Сразу запустить агента по новой теме (отобрать из имеющихся постов).
        run_topic_agent_async(topic_id=res["id"])
        return JSONResponse({"ok": True, "topic": res}, status_code=201)
    if method == "DELETE":
        name = request.query_params.get("name", "").strip()
        if remove_topic(name):
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "Тема не найдена"}, status_code=404)
    return JSONResponse({"error": "Метод не поддерживается"}, status_code=405)


async def api_topic_posts(request: Request) -> JSONResponse:
    """GET — хронология темы; POST — ручное добавление поста;
    DELETE — удаление записи из хронологии."""
    name = request.query_params.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Укажите ?name= темы"}, status_code=400)
    topic = get_topic(name)
    if not topic:
        return JSONResponse({"error": "Тема не найдена"}, status_code=404)
    method = request.method
    if method == "GET":
        # «Движок» собирает посты, которым присвоен тег темы (mode='ai'/'manual').
        posts = get_tagged_posts(topic["id"])
        total = get_tagged_total(topic["id"])
        return JSONResponse({"topic": topic, "total": total, "posts": posts})
    if method == "POST":
        # Ручное присвоение тега посту из общей ленты (mode='manual').
        data = await request.json()
        post_id = data.get("post_id")
        if post_id is None:
            return JSONResponse({"error": "Укажите post_id"}, status_code=400)
        row = tag_post(topic["id"], int(post_id), mode="manual")
        if not row:
            return JSONResponse({"error": "Пост не найден в ленте"}, status_code=404)
        return JSONResponse({"ok": True, "post": row}, status_code=201)
    if method == "DELETE":
        # Ручное удаление поста из темы + признак исключения: агент не
        # вернёт его автоматически, только по явному сбросу (reset) или
        # повторному ручному добавлению.
        post_id = request.query_params.get("post_id")
        if not post_id:
            return JSONResponse({"error": "Укажите ?post_id="}, status_code=400)
        if exclude_post(topic["id"], int(post_id)):
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "Запись не найдена"}, status_code=404)
    return JSONResponse({"error": "Метод не поддерживается"}, status_code=405)


async def api_topic_run(request: Request) -> JSONResponse:
    """POST /api/topics/run?name=... — запустить агента для одной темы сейчас."""
    name = request.query_params.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Укажите ?name= темы"}, status_code=400)
    topic = get_topic(name)
    if not topic:
        return JSONResponse({"error": "Тема не найдена"}, status_code=404)
    run_topic_agent_async(topic_id=topic["id"])
    return JSONResponse({"ok": True, "message": "Агент запущен"})


async def api_topic_run_all(request: Request) -> JSONResponse:
    """POST /api/topics/run-all — запустить агента для всех активных тем."""
    count = 0
    for t in list_topics():
        if t.get("active"):
            run_topic_agent_async(topic_id=t["id"])
            count += 1
    return JSONResponse({"ok": True, "started": count})


async def api_topic_toggle(request: Request) -> JSONResponse:
    """POST /api/topics/toggle?name=...&active=1|0 — включить/выключить тему."""
    name = request.query_params.get("name", "").strip()
    raw = str(request.query_params.get("active", "1") or "1").strip().lower()
    active = raw not in ("0", "false", "off", "no", "")
    topic = get_topic(name)
    if not topic:
        return JSONResponse({"error": "Тема не найдена"}, status_code=404)
    set_topic_active(name, bool(active))
    return JSONResponse({"ok": True, "active": bool(active)})


async def api_topic_reset_exclusions(request: Request) -> JSONResponse:
    """POST /api/topics/reset?name=...[&post_id=...] — снять признак исключения.

    Без post_id снимает все исключения темы; с post_id — только для одного
    поста. Это «явный сброс»: после него агент сможет снова отобрать пост(ы).
    """
    name = request.query_params.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Укажите ?name= темы"}, status_code=400)
    topic = get_topic(name)
    if not topic:
        return JSONResponse({"error": "Тема не найдена"}, status_code=404)
    raw_post = request.query_params.get("post_id")
    post_id = int(raw_post) if raw_post else None
    removed = reset_exclusions(topic["id"], post_id)
    return JSONResponse({"ok": True, "removed": removed})


async def api_config(request: Request) -> JSONResponse:
    """GET — текущий конфиг провайдера/агента; POST — сохранить.

    Конфиг хранится в config.json (перечитывается load_config() при каждом
    обращении агента, поэтому перезапуск не нужен).
    """
    if request.method == "GET":
        return JSONResponse(load_config())
    if request.method == "POST":
        try:
            data = await request.json()
        except Exception:
            data = {}
        cfg = load_config()
        # Обновляем только известные поля поверх текущего конфига.
        for k in ("provider", "model", "systemPrompt"):
            if k in data and data[k] not in (None, ""):
                cfg[k] = data[k]
        sched = data.get("schedule")
        if isinstance(sched, dict):
            cfg.setdefault("schedule", {})
            for sk, sv in sched.items():
                if sv in (None, ""):
                    continue
                try:
                    cfg["schedule"][sk] = int(sv)
                except (TypeError, ValueError):
                    cfg["schedule"][sk] = sv
        provs = data.get("providers")
        if isinstance(provs, dict):
            cfg.setdefault("providers", {})
            for pname, pblock in provs.items():
                if isinstance(pblock, dict):
                    cfg["providers"].setdefault(pname, {})
                    cfg["providers"][pname].update(pblock)
        try:
            save_config(cfg)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        return JSONResponse({"ok": True})
    return JSONResponse({"error": "Метод не поддерживается"}, status_code=405)


async def api_config_test(request: Request) -> JSONResponse:
    """POST /api/config/test — проверить связь с моделью прямо сейчас."""
    if request.method != "POST":
        return JSONResponse({"error": "Метод не поддерживается"}, status_code=405)
    try:
        res = test_connection()
    except Exception as e:
        res = {"ok": False, "error": str(e)}
    return JSONResponse(res)


def register_ui(mcp):
    """Зарегистрировать маршруты веб-интерфейса на MCP-сервере."""
    mcp.custom_route("/", methods=["GET"])(lambda request: RedirectResponse("/ui"))
    mcp.custom_route("/ui", methods=["GET"])(ui_index)
    mcp.custom_route("/api/sources", methods=["GET", "POST"])(api_sources)
    mcp.custom_route("/api/posts", methods=["GET"])(api_posts)
    mcp.custom_route("/api/refresh/posts", methods=["POST"])(api_refresh_posts)
    mcp.custom_route("/api/rsshub", methods=["GET"])(api_rsshub)
    # «Мои темы»: темы + их хронология + запуск агента
    mcp.custom_route("/api/topics", methods=["GET", "POST", "DELETE"])(api_topics)
    mcp.custom_route("/api/topics/posts", methods=["GET", "POST", "DELETE"])(api_topic_posts)
    mcp.custom_route("/api/topics/run", methods=["POST"])(api_topic_run)
    mcp.custom_route("/api/topics/run-all", methods=["POST"])(api_topic_run_all)
    mcp.custom_route("/api/topics/toggle", methods=["POST"])(api_topic_toggle)
    mcp.custom_route("/api/topics/reset", methods=["POST"])(api_topic_reset_exclusions)
    # Настройки провайдера / модели ИИ (карточка в «Мои темы»)
    mcp.custom_route("/api/config", methods=["GET", "POST"])(api_config)
    mcp.custom_route("/api/config/test", methods=["POST"])(api_config_test)
