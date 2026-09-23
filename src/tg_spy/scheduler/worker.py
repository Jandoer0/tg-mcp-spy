"""Фоновый планировщик: авто-обновление ленты и периодический запуск агента.

Работает в отдельном демоне-потоке внутри процесса. Каждые 30 с проверяет
расписание из config.json: обновляет ленту и для каждой активной темы
запускает локальный ИИ-агент по её интервалу. Прогоны агента отправляются
в пул потоков с ограниченной конкурентностью, чтобы не забивать слабую
модель и не блокировать тик планировщика (старый код запускал их
последовательно и синхронно).
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import load_config
from ..db import list_topics
from ..ingest.refresh import refresh_all_sources
from ..topics.agent import run_topic_agent

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()
_TICK_SECONDS = 30
# Ограничиваем одновременные прогоны агента (слабая локальная модель).
_agent_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="topic-agent")


def _tick() -> None:
    try:
        cfg = load_config()
        sched = cfg.schedule
        if not sched.enabled:
            return
        now = time.time()

        feed_min = max(1, int(sched.feed_refresh_minutes))
        if now - _last_feed >= feed_min * 60:
            try:
                r = refresh_all_sources(days=1)
                logger.info("Авто-обновление ленты: %s", r)
            except Exception as e:  # noqa: BLE001
                logger.error("Ошибка авто-обновления ленты: %s", e)
            _last_feed = now

        topic_min = max(1, int(sched.topic_minutes))
        for t in list_topics():
            if not t.get("active"):
                continue
            interval = max(1, int(t.get("schedule_minutes") or topic_min))
            lr = _last_run.get(t["id"], 0.0)
            if now - lr >= interval * 60:
                _last_run[t["id"]] = now
                _agent_pool.submit(_run_topic, t["id"])
    except Exception as e:  # noqa: BLE001
        logger.error("Ошибка планировщика: %s", e)


def _run_topic(topic_id: int) -> None:
    try:
        res = run_topic_agent(topic_id=topic_id)
        logger.info("Агент по теме id=%s: %s", topic_id, res)
    except Exception as e:  # noqa: BLE001
        logger.error("Ошибка агента по теме id=%s: %s", topic_id, e)


# Состояние между тиками.
_last_feed = 0.0
_last_run: dict[int, float] = {}


def start_scheduler() -> None:
    """Запустить планировщик (идемпотентно)."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            return
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _tick, "interval", seconds=_TICK_SECONDS, id="tick",
            max_instances=1, coalesce=True,
        )
        scheduler.start()
        _scheduler = scheduler
        logger.info("Планировщик агента запущен")


def run_forever() -> None:
    """Запустить планировщик и не возвращаться (режим `worker`)."""
    start_scheduler()
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
