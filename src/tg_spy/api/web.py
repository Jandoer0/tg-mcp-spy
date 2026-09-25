"""Веб-транспорт: обработчики HTTP, регистрируемые на MCP-сервере.

MCP-сервер выступает корневым ASGI-приложением (проверенный паттерн:
``mcp.streamable_http_app`` отдаёт /mcp, а веб-маршруты и статика
добавляются через ``mcp.custom_route``). Логика здесь тонкая — вся работа
делегируется слоям db / ingest / topics / config.
"""
from __future__ import annotations

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)

from ..config import AppConfig, load_config, save_config
from ..db import (
    add_source,
    get_posts,
    get_posts_by_tag,
    get_posts_by_tags,
    get_source,
    list_sources,
)
from ..ingest import rss
from ..ingest.refresh import refresh_all_sources
from ..topics import agent, service
from ..topics import editor as editor_svc
from ..config import get_provider, load_config

WEB_DIR = Path(__file__).parent.parent / "web" / "static"


# --------------------------------------------------------------------------- #
# Страница и статика
# --------------------------------------------------------------------------- #
async def root_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse("/ui")


async def ui_index(request: Request) -> HTMLResponse:
    # no-cache — иначе браузер долго держит старые JS/CSS и правки не видны.
    return HTMLResponse(
        (WEB_DIR / "index.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache"},
    )


async def static_handler(request: Request) -> FileResponse:
    rel = request.path_params.get("path", "")
    # защита от выхода за пределы каталога
    candidate = (WEB_DIR / rel).resolve()
    if not str(candidate).startswith(str(WEB_DIR.resolve())) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="not found")
    # no-cache — статику пересобираем в образе; пусть браузер всегда ревалидирует.
    return FileResponse(str(candidate), headers={"Cache-Control": "no-cache"})


# --------------------------------------------------------------------------- #
# Подписки
# --------------------------------------------------------------------------- #
async def api_sources(request: Request) -> JSONResponse:
    if request.method == "GET":
        return JSONResponse(
            [
                {
                    "id": s["id"],
                    "kind": s["kind"],
                    "name": s["name"],
                    "url": s["url"],
                    "added_at": s["added_at"],
                }
                for s in list_sources()
            ]
        )
    # POST
    body = await _json(request, default={})
    kind = (body.get("kind") or "").strip().lower()
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip() or None
    if not name:
        return JSONResponse({"error": "Укажите name"}, status_code=400)
    if kind not in ("telegram", "rss"):
        return JSONResponse({"error": "kind должен быть telegram или rss"}, status_code=400)
    if kind == "rss" and not url:
        return JSONResponse({"error": "Для rss нужно указать url"}, status_code=400)
    src = add_source(kind, name, url)
    return JSONResponse({"ok": True, "source": src}, status_code=201)


async def api_source_delete(request: Request) -> JSONResponse:
    name = request.path_params.get("name", "")
    from ..db import remove_source

    if not remove_source(name):
        return JSONResponse({"error": "Подписка не найдена"}, status_code=404)
    return JSONResponse({"ok": True})


# --------------------------------------------------------------------------- #
# Посты
# --------------------------------------------------------------------------- #
def _post_json(p: dict) -> dict:
    """Сериализовать пост для фронта, включая поля ИИ-редактора."""
    return {
        "id": p["id"],
        "date": p["date"],
        "text": p["text"],
        "text_edited": p.get("text_edited"),
        "editor_status": p.get("editor_status") or "none",
        "editor_active": int(p.get("editor_active") or 0),
        "url": p["url"],
        "source": p.get("source", ""),
        "kind": p.get("kind", ""),
    }


async def api_posts(request: Request) -> JSONResponse:
    source = request.query_params.get("source", "").strip().lower().lstrip("@")
    kind = request.query_params.get("kind", "").strip().lower()
    tag = request.query_params.get("tag", "").strip()
    tags_raw = request.query_params.get("tags", "").strip()
    if kind not in ("telegram", "rss"):
        kind = ""
    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))
    try:
        offset = int(request.query_params.get("offset", "0"))
    except ValueError:
        offset = 0
    offset = max(0, offset)

    # Фильтр по нескольким тегам (логическое И): посты, отмеченные всеми ими.
    if tags_raw:
        tag_list = [t.strip() for t in tags_raw.split(",") if t.strip()]
        if tag_list:
            rows = get_posts_by_tags(tag_list, limit, offset)
            return JSONResponse(
                {
                    "global": True,
                    "tags": tag_list,
                    "posts": [_post_json(p) for p in rows],
                }
            )

    if tag:
        rows = get_posts_by_tag(tag, limit, offset)
        return JSONResponse(
            {
                "global": True,
                "tag": tag,
                "posts": [_post_json(p) for p in rows],
            }
        )

    if source:
        src = get_source(source)
        if not src:
            return JSONResponse({"error": "Подписка не найдена"}, status_code=404)
        rows = get_posts([src["id"]], "1970-01-01", limit, offset)
        return JSONResponse(
            {
                "source": source, "kind": src["kind"], "global": False,
                "posts": [_post_json(p) for p in rows],
            }
        )

    srcs = list_sources(kind) if kind else list_sources()
    rows = get_posts([s["id"] for s in srcs], "1970-01-01", limit, offset)
    return JSONResponse(
        {
            "global": True, "kind": kind,
            "posts": [_post_json(p) for p in rows],
        }
    )


async def api_refresh_posts(request: Request) -> JSONResponse:
    body = await _json(request, default={})
    try:
        days = int(body.get("days", 1))
    except (TypeError, ValueError):
        days = 1
    days = max(1, min(days, 30))
    kind = (body.get("kind") or "").strip()
    try:
        result = refresh_all_sources(days=days, kind=kind)
        return JSONResponse({"ok": True, **result})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_rsshub(request: Request) -> JSONResponse:
    username = request.query_params.get("username", "").strip()
    base = request.query_params.get("base", "").strip() or rss.DEFAULT_RSSHUB
    if not username:
        return JSONResponse({"error": "Укажите ?username=..."}, status_code=400)
    return JSONResponse({"url": rss.rsshub_telegram_url(base, username)})


async def api_posts_tags(request: Request) -> JSONResponse:
    """Вернуть теги пользователя (темы) для списка постов.

    query: ?ids=1,2,3  →  {"1": [{"name", "tag"}], ...}
    """
    raw = request.query_params.get("ids", "").strip()
    if not raw:
        return JSONResponse({})
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    if not ids:
        return JSONResponse({})
    from ..db import get_post_topics

    mapping = get_post_topics(ids)
    return JSONResponse({str(k): v for k, v in mapping.items()})


async def api_posts_editor(request: Request) -> JSONResponse:
    """Состояние ИИ-редактора для списка постов.

    query: ?ids=1,2,3  →  {"1": {"status", "active", "has_edited"}, ...}
    """
    raw = request.query_params.get("ids", "").strip()
    if not raw:
        return JSONResponse({})
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    if not ids:
        return JSONResponse({})
    from ..db import get_posts_editor_status

    return JSONResponse(get_posts_editor_status(ids))


async def api_editor_run(request: Request) -> JSONResponse:
    """Пакетная ИИ-редактура постов за последние N дней (или все).

    body: {"days": 7}  (0 или отсутствие — все посты). Запуск в фоне.
    """
    body = await _json(request, default={})
    days = body.get("days")
    if days in (None, "", 0):
        days = None
    else:
        try:
            days = int(days)
            days = max(0, min(days, 365))
        except (TypeError, ValueError):
            days = None
    editor_svc.run_editor_async(days=days)
    return JSONResponse({"ok": True, "message": "ИИ-редактор запущен (пакетная обработка)"})


async def api_editor_post(request: Request) -> JSONResponse:
    """Персональная редактура одного поста и переключение состояния.

    - POST   /api/editor/post?post_id=  → запустить редактуру поста (фон),
    - POST   /api/editor/post/active?post_id=&active=1  → показать оригинал/редакцию,
    - DELETE /api/editor/post?post_id=  → удалить сохранённую редакцию.
    """
    post_id_raw = request.query_params.get("post_id", "").strip()
    if not post_id_raw.isdigit():
        return JSONResponse({"error": "Укажите post_id"}, status_code=400)
    post_id = int(post_id_raw)

    # Переключение «показывать редакцию» (active) — отдельный маршрут
    # /api/editor/post/active?post_id=&active=1.
    if request.url.path.rstrip("/").endswith("/active"):
        active_raw = str(request.query_params.get("active", "1") or "1").strip()
        active = active_raw not in ("0", "false", "off", "no")
        if not editor_svc.set_active(post_id, active):
            return JSONResponse({"error": "Пост не найден"}, status_code=404)
        return JSONResponse({"ok": True, "active": active})

    if request.method == "DELETE":
        if not editor_svc.remove_edition(post_id):
            return JSONResponse({"error": "Пост не найден"}, status_code=404)
        return JSONResponse({"ok": True})

    # POST — запустить редактуру.
    editor_svc.edit_post_async(post_id)
    return JSONResponse({"ok": True, "message": "Редактура поста запущена"})


# --------------------------------------------------------------------------- #
# «Мои темы»
# --------------------------------------------------------------------------- #
async def api_topics(request: Request) -> JSONResponse:
    if request.method == "GET":
        return JSONResponse(_list_topics())
    if request.method == "POST":
        body = await _json(request, default={})
        name = (body.get("name") or "").strip()
        tag = (body.get("tag") or "").strip()
        description = (body.get("description") or "").strip()
        try:
            sched = int(body.get("schedule_minutes", 1440))
        except (TypeError, ValueError):
            sched = 1440
        if not name or not tag:
            return JSONResponse({"error": "Укажите name и tag"}, status_code=400)
        res = service.create_topic(name, tag, sched, description=description)
        if not res.get("ok"):
            return JSONResponse({"error": res.get("error")}, status_code=400)
        return JSONResponse({"ok": True, "topic": res}, status_code=201)
    # DELETE
    name = request.query_params.get("name", "").strip()
    if not service.delete_topic(name):
        return JSONResponse({"error": "Тема не найдена"}, status_code=404)
    return JSONResponse({"ok": True})


async def api_topics_posts(request: Request) -> JSONResponse:
    name = request.query_params.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Укажите ?name= темы"}, status_code=400)
    if request.method == "GET":
        detail = service.get_topic_detail(name)
        if not detail:
            return JSONResponse({"error": "Тема не найдена"}, status_code=404)
        return JSONResponse(detail)
    if request.method == "POST":
        body = await _json(request, default={})
        post_id = body.get("post_id")
        if post_id is None:
            return JSONResponse({"error": "Укажите post_id"}, status_code=400)
        row = service.add_post_manual(name, int(post_id))
        if not row:
            return JSONResponse({"error": "Пост не найден в ленте"}, status_code=404)
        return JSONResponse({"ok": True, "post": row}, status_code=201)
    # DELETE
    post_id = request.query_params.get("post_id")
    if not post_id:
        return JSONResponse({"error": "Укажите ?post_id="}, status_code=400)
    if not service.remove_post(name, int(post_id)):
        return JSONResponse({"error": "Запись не найдена"}, status_code=404)
    return JSONResponse({"ok": True})


async def api_topics_run(request: Request) -> JSONResponse:
    name = request.query_params.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Укажите ?name= темы"}, status_code=400)
    if not service.get_topic(name):
        return JSONResponse({"error": "Тема не найдена"}, status_code=404)
    service.run_agent_async(name)
    return JSONResponse({"ok": True, "message": "Агент запущен"})


async def api_topics_run_all(request: Request) -> JSONResponse:
    count = service.run_all_agents()
    return JSONResponse({"ok": True, "started": count})


async def api_topics_toggle(request: Request) -> JSONResponse:
    name = request.query_params.get("name", "").strip()
    raw = str(request.query_params.get("active", "1") or "1").strip().lower()
    is_active = raw not in ("0", "false", "off", "no", "")
    if not service.set_active(name, is_active):
        return JSONResponse({"error": "Тема не найдена"}, status_code=404)
    return JSONResponse({"ok": True, "active": is_active})


async def api_topics_reset(request: Request) -> JSONResponse:
    name = request.query_params.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Укажите ?name= темы"}, status_code=400)
    if not service.get_topic(name):
        return JSONResponse({"error": "Тема не найдена"}, status_code=404)
    raw_post = request.query_params.get("post_id")
    post_id = int(raw_post) if raw_post else None
    removed = service.reset_exclusions(name, post_id)
    return JSONResponse({"ok": True, "removed": removed})


# --------------------------------------------------------------------------- #
# Настройки провайдера / модели ИИ
# --------------------------------------------------------------------------- #
async def api_config(request: Request) -> JSONResponse:
    if request.method == "GET":
        return JSONResponse(load_config().to_legacy_dict())
    # POST
    data = await _json(request, default={})
    cfg = load_config()
    cur = cfg.to_legacy_dict()
    
    # Сохранение классификатора
    if "classifier" in data:
        c_data = data["classifier"]
        cur["classifier"]["provider"] = c_data.get("provider", cur["classifier"]["provider"])
        cur["classifier"]["model"] = c_data.get("model", cur["classifier"]["model"])
    
    # Сохранение редактора
    if "editor" in data:
        e_data = data["editor"]
        cur["editor"]["provider"] = e_data.get("provider", cur["editor"]["provider"])
        cur["editor"]["model"] = e_data.get("model", cur["editor"]["model"])

    # Обновление провайдеров (глобальный список доступных коннектов)
    if "providers" in data:
        provs = data["providers"]
        if isinstance(provs, dict):
            cur.setdefault("providers", {})
            for pname, pblock in provs.items():
                if isinstance(pblock, dict):
                    cur["providers"].setdefault(pname, {})
                    cur["providers"][pname].update(pblock)

    if "timezone" in data:
        cur["timezone"] = data["timezone"] or ""
        
    sched = data.get("schedule")
    if isinstance(sched, dict):
        cur.setdefault("schedule", {})
        for sk, sv in sched.items():
            if sv in (None, ""): continue
            try: cur["schedule"][sk] = int(sv)
            except (TypeError, ValueError): cur["schedule"][sk] = sv
            
    try:
        new_cfg = AppConfig.from_legacy_dict(cur)
        save_config(new_cfg)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True})


async def api_config_test(request: Request) -> JSONResponse:
    provider_type = request.query_params.get("type", "classifier")
    try:
        return JSONResponse(agent.test_connection(provider_name=provider_type))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)})


async def api_config_models(request: Request) -> JSONResponse:
    """Запросить у провайдера список доступных моделей.

    Тело запроса: {"baseUrl": "...", "apiKey": "..."} (адрес берётся из поля
    ввода, а не из сохранённого конфига — чтобы пользователь мог проверить
    новый адрес до сохранения). Если тело пустое — берётся сохранённый конфиг.
    """
    body = await _json(request, default={})
    base_url = (body.get("baseUrl") or "").strip()
    api_key = (body.get("apiKey") or "").strip()
    if not base_url:
        cfg = load_config()
        # По умолчанию берем провайдера классификатора
        prov = get_provider(cfg, provider_name=cfg.classifier_provider)
        base_url = prov.base_url or ""
        api_key = api_key or (prov.api_key or "")
    try:
        return JSONResponse(agent.list_models(base_url, api_key))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)})


# --------------------------------------------------------------------------- #
# Вспомогательное
# --------------------------------------------------------------------------- #
async def _json(request: Request, default):
    try:
        return await request.json()
    except Exception:
        return default


def _list_topics():
    from ..db import list_topics

    return list_topics()
