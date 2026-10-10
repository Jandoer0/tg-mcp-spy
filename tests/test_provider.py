"""Тесты единой логики работы ролей с провайдером.

Классификатор и редактор имеют РАЗНЫЕ конфигурации провайдеров/моделей,
но работают через ОДНУ функцию (provider.call_role): одинаковые повторы,
одинаковая фиксация ошибок (last_provider_error) и одинаковая проверка
соединения (test_connection) с системным промптом своей роли.
"""
import json

import httpx
import pytest
import respx

from mcp_news.config import load_config, role_system_prompt
from mcp_news.topics import provider

CLASSIFIER_URL = "http://127.0.0.1:11434/v1/chat/completions"
EDITOR_URL = "http://127.0.0.1:11435/v1/chat/completions"


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_roles_use_their_own_providers():
    # У каждой роли свой провайдер из конфига, логика вызова — одна.
    with respx.mock:
        c_route = respx.post(CLASSIFIER_URL).mock(return_value=_ok("классификация"))
        e_route = respx.post(EDITOR_URL).mock(return_value=_ok("правка"))

        r1 = provider.call_role("classifier", [{"role": "user", "content": "пост"}])
        r2 = provider.call_role(
            "editor", [{"role": "user", "content": "пост"}], output_format="text"
        )

        assert r1.ok and r1.content == "классификация"
        assert r2.ok and r2.content == "правка"
        assert c_route.called and e_route.called
        assert provider.last_provider_error("classifier") is None
        assert provider.last_provider_error("editor") is None


def test_failure_records_same_error_for_both_roles():
    # Ошибка провайдера фиксируется одинаково для обеих ролей.
    with respx.mock:
        respx.post(CLASSIFIER_URL).mock(side_effect=httpx.ConnectError("boom"))
        respx.post(EDITOR_URL).mock(side_effect=httpx.ConnectError("boom"))

        r1 = provider.call_role("classifier", [{"role": "user", "content": "x"}])
        r2 = provider.call_role("editor", [{"role": "user", "content": "x"}])

        assert not r1.ok and not r2.ok
        assert provider.last_provider_error("classifier")
        assert provider.last_provider_error("editor")

    # Успешный вызов сбрасывает ошибку роли — одинаково для обеих.
    with respx.mock:
        respx.post(EDITOR_URL).mock(return_value=_ok("ok"))
        assert provider.call_role("editor", [{"role": "user", "content": "x"}]).ok
        assert provider.last_provider_error("editor") is None


@pytest.mark.parametrize("role,url", [("classifier", CLASSIFIER_URL), ("editor", EDITOR_URL)])
def test_connection_uses_role_prompt_and_provider(role, url):
    # «Проверить соединение» — одна логика для обеих ролей: свой провайдер,
    # свой системный промпт, одинаковые оповещения.
    with respx.mock:
        route = respx.post(url).mock(return_value=_ok("на связи"))
        res = provider.test_connection(role)

        assert res["ok"]
        assert res["message"].startswith("Связь установлена")
        payload = json.loads(route.calls.last.request.content)
        system = [m for m in payload["messages"] if m["role"] in ("system", "developer")]
        assert system, "должен быть системный промпт"
        assert system[0]["content"] == role_system_prompt(load_config(), role)


def test_connection_error_same_shape_for_both_roles():
    # Одинаковая структура ответа об ошибке у обеих ролей.
    with respx.mock:
        respx.post(CLASSIFIER_URL).mock(side_effect=httpx.ConnectError("boom"))
        respx.post(EDITOR_URL).mock(side_effect=httpx.ConnectError("boom"))

        for role in ("classifier", "editor"):
            res = provider.test_connection(role)
            assert res["ok"] is False
            assert res["error"]
            assert "model" in res


def test_timeout_no_retry():
    # Таймаут не должен повторяться (общее правило для ролей).
    # Это предотвращает многоминутные зависания на одном длинном посте.
    with respx.mock:
        # Любой запрос вызывает Timeout (через side_effect httpx.ReadTimeout)
        respx.post(EDITOR_URL).mock(side_effect=httpx.ReadTimeout("request timed out"))
        
        # Вызываем роль (по умолчанию 3 попытки в provider.py)
        result = provider.call_role("editor", [{"role": "user", "content": "test"}])
        
        # Должна быть только ОДНА попытка
        assert result.attempts == 1
        assert not result.ok
        assert "timed out" in result.error.lower()
        # Убеждаемся, что mock.post был вызван ровно 1 раз
        assert respx.post(EDITOR_URL).call_count == 1
