"""Фоновый планировщик: авто-обновление ленты и периодический запуск агента.

Работает в отдельном демоне-потоке внутри процесса uvicorn. Каждые ~30 c
проверяет расписание из config.json: обновляет ленту и для каждой активной
темы запускает локальный ИИ-агент, который дособирает релевантные посты.
"""
import logging
import threading
import time

from config import load_config
from db import list_topics
from webui import refresh_all_sources
from agent import run_topic_agent

logger = logging.getLogger(__name__)

_scheduler_thread = None
_scheduler_lock = threading.Lock()
_TICK_SECONDS = 30


def _loop() -> None:
    last_feed = 0.0
    last_run: dict[int, float] = {}
    while True:
        try:
            cfg = load_config()
            sched = cfg.get("schedule") or {}
            if sched.get("enabled", True):
                now = time.time()

                feed_min = max(1, int(sched.get("feedRefreshMinutes", 60)))
                if now - last_feed >= feed_min * 60:
                    try:
                        r = refresh_all_sources(days=1)
                        logger.info("Авто-обновление ленты: %s", r)
                    except Exception as e:
                        logger.error("Ошибка авто-обновления ленты: %s", e)
                    last_feed = now

                topic_min = max(1, int(sched.get("topicMinutes", 30)))
                for t in list_topics():
                    if not t.get("active"):
                        continue
                    interval = max(1, int(t.get("schedule_minutes") or topic_min))
                    lr = last_run.get(t["id"], 0.0)
                    if now - lr >= interval * 60:
                        try:
                            res = run_topic_agent(topic_id=t["id"])
                            logger.info("Агент по теме %s: %s", t.get("name"), res)
                        except Exception as e:
                            logger.error("Ошибка агента по теме %s: %s", t.get("name"), e)
                        last_run[t["id"]] = now
        except Exception as e:
            logger.error("Ошибка планировщика: %s", e)
        time.sleep(_TICK_SECONDS)


def start_scheduler() -> None:
    """Запустить планировщик (идемпотентно)."""
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return
        _scheduler_thread = threading.Thread(
            target=_loop, name="topic-agent-scheduler", daemon=True
        )
        _scheduler_thread.start()
        logger.info("Планировщик агента запущен")
