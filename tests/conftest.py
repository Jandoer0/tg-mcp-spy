"""Общая настройка тестов: изолированная БД и конфиг в temp-каталоге."""
import os

import pytest

_DB = "/tmp/tg_spy_pytest.db"
_CFG = "/tmp/tg_spy_pytest_config.json"
for _p in (_DB, _CFG):
    try:
        os.remove(_p)
    except FileNotFoundError:
        pass

os.environ["DB_PATH"] = _DB
os.environ["AGENT_CONFIG"] = _CFG
# Указываем локальный эндпоинт, чтобы agent-тесты мокали его предсказуемо.
os.environ["AGENT_BASE_URL"] = "http://127.0.0.1:11434/v1"


@pytest.fixture(autouse=True)
def _clean_db():
    """Очищаем таблицы между тестами."""
    from tg_spy.db import get_conn, init_db

    init_db()
    yield
    conn = get_conn()
    conn.execute("DELETE FROM topic_exclusions")
    conn.execute("DELETE FROM posts_tags")
    conn.execute("DELETE FROM posts")
    conn.execute("DELETE FROM topics")
    conn.execute("DELETE FROM sources")
    conn.commit()
    conn.close()


@pytest.fixture()
def conn():
    from tg_spy.db import get_conn, init_db

    init_db()
    return get_conn()
