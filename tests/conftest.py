"""Общая настройка тестов: изолированная БД и конфиг в temp-каталоге."""
import os

import pytest

_DB = "/tmp/mcp_news_pytest.db"
_CFG = "/tmp/mcp_news_pytest_config.json"
for _p in (_DB, _CFG):
    try:
        os.remove(_p)
    except FileNotFoundError:
        pass

os.environ["DB_PATH"] = _DB
os.environ["AGENT_CONFIG"] = _CFG
# Указываем локальные эндпоинты ОБЕИХ ролей (у классификатора и редактора
# свои провайдеры), чтобы agent/provider-тесты мокали их предсказуемо
# и не зависели от реальной Ollama на хосте.
os.environ["AGENT_CLASSIFIER_URL"] = "http://127.0.0.1:11434/v1"
os.environ["AGENT_EDITOR_URL"] = "http://127.0.0.1:11435/v1"


@pytest.fixture(autouse=True)
def _clean_db():
    """Очищаем таблицы между тестами."""
    from mcp_news.db import get_conn, init_db

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
    from mcp_news.db import get_conn, init_db

    init_db()
    return get_conn()
