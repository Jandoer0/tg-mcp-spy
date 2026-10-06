"""Общий OpenAI-совместимый клиент для ИИ-классификатора и ИИ-редактора.

Роли используют разные настройки провайдеров и моделей (у каждой роли свой
provider/model в конфиге), но логика работы у них одна: один и тот же
транспорт, таймауты, повторы, обработка ответа и ошибок, одинаковые
оповещения. Оба потребителя (классификатор и редактор) вызывают одну и ту
же функцию :func:`call_role`.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import threading
import time
from typing import Any, Optional

import httpx

from ..config import (
    AppConfig,
    ProviderConfig,
    get_provider,
    load_config,
    role_model,
    role_system_prompt,
)

logger = logging.getLogger(__name__)

# --- Общие параметры обращения к модели (одинаковы для обеих ролей) ---
# Число повторных попыток обращения к модели при сбоях.
ROLE_RETRIES = int(os.environ.get("AGENT_RETRIES", "2"))
# Пауза между попытками (сек), растёт линейно.
ROLE_RETRY_BACKOFF = float(os.environ.get("AGENT_RETRY_BACKOFF", "1.5"))
# Таймаут одного запроса к модели (сек).
ROLE_REQUEST_TIMEOUT = float(os.environ.get("AGENT_REQUEST_TIMEOUT", "300.0"))

# Последняя ошибка провайдера по каждой роли (для одинаковых оповещений в UI).
_last_role_errors: dict[str, Optional[str]] = {"classifier": None, "editor": None}

# Роли, остановленные пользователем (выключен переключатель). Пока роль в
# этом множестве, новые запросы к её провайдеру отклоняются мгновенно —
# выключение переключателя останавливает не только текущий запрос
# (закрытие соединения), но и весь пакет, не давая ему продолжать работу.
_stopped_roles: set[str] = set()


def role_stopped(role: str) -> bool:
    """Остановлена ли роль выключением переключателя."""
    return role in _stopped_roles


def resume_role(role: str) -> None:
    """Снять признак остановки роли (при повторном включении переключателя)."""
    _stopped_roles.discard(role)


def last_provider_error(role: str = "classifier") -> Optional[str]:
    """Последняя ошибка обращения к провайдеру роли (роль — та же логика,
    те же тексты ошибок для классификатора и редактора)."""
    return _last_role_errors.get(role)

# Реестр активных запросов. Он общий для обеих ролей, а kind позволяет
# остановить только классификатор или только редактор.
_active_requests: dict[int, tuple[httpx.Client, str]] = {}
_active_lock = threading.Lock()


@dataclass(frozen=True)
class ProviderCallResult:
    """Единый результат обращения к модели для обеих ролей."""

    ok: bool
    content: Optional[str]
    error: Optional[str]
    provider_name: str
    model: str
    url: str
    attempts: int = 0
    aborted: bool = False
    status_code: Optional[int] = None

    @classmethod
    def failure(
        cls,
        *,
        provider_name: str,
        model: str,
        url: str,
        error: str,
        attempts: int = 0,
        aborted: bool = False,
        status_code: Optional[int] = None,
    ) -> "ProviderCallResult":
        return cls(
            ok=False,
            content=None,
            error=error,
            provider_name=provider_name,
            model=model,
            url=url,
            attempts=attempts,
            aborted=aborted,
            status_code=status_code,
        )


def abort_requests(kind: str | None = None) -> int:
    """Прервать активные HTTP-запросы всех ролей или одной роли.

    Кроме закрытия in-flight соединений помечает роль как остановленную:
    новые запросы к ней отклоняются сразу (до повторного включения —
    :func:`resume_role`), поэтому модель гарантированно замолкает
    сразу после выключения переключателя.
    """
    with _active_lock:
        targets = [
            (client_id, _active_requests[client_id])
            for client_id in list(_active_requests)
            if kind is None or _active_requests[client_id][1] == kind
        ]
        for client_id, _ in targets:
            del _active_requests[client_id]

    if kind:
        _stopped_roles.add(kind)
    else:
        _stopped_roles.update(("classifier", "editor"))

    interrupted = 0
    for _client_id, (client, _provider_name) in targets:
        try:
            # Флаг читается в потоке запроса после закрытия клиента, поэтому
            # остановка не запускает повторную попытку.
            client._tg_aborted = True  # type: ignore[attr-defined]
            client.close()
            interrupted += 1
        except Exception:  # pragma: no cover - зависит от гонки закрытия
            pass
    return interrupted


def _exception_message(error: Exception) -> str:
    """Сделать непустое и пригодное для UI описание исключения."""
    text = str(error).strip()
    return text or error.__class__.__name__


def _response_error(response: httpx.Response) -> str:
    """Извлечь понятную ошибку из JSON-ответа провайдера."""
    detail: Any = None
    try:
        data = response.json()
        if isinstance(data, dict):
            detail = data.get("error") or data.get("message") or data.get("detail")
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("detail") or detail
    except Exception:
        pass

    if detail:
        return f"HTTP {response.status_code}: {detail}"
    return f"HTTP {response.status_code}: провайдер вернул ошибку"


def _message_content(data: Any) -> Optional[str]:
    """Извлечь текст из стандартного OpenAI-совместимого ответа."""
    try:
        message = data["choices"][0]["message"]
        content = message.get("content") if isinstance(message, dict) else None
    except (KeyError, IndexError, TypeError):
        return None

    if isinstance(content, str):
        return content.strip() or None
    # Некоторые OpenAI-совместимые шлюзы отдают content массивом частей.
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        text = "".join(parts).strip()
        return text or None
    return None


class ProviderClient:
    """Общий клиент chat/completions с настройками конкретной роли."""

    def __init__(
        self,
        provider_name: str,
        *,
        config: AppConfig | None = None,
        provider: ProviderConfig | None = None,
        model: str | None = None,
    ) -> None:
        if provider_name not in ("classifier", "editor"):
            raise ValueError(f"Неизвестная роль провайдера: {provider_name}")

        self.config = config or load_config()
        self.provider_name = provider_name
        self.provider = provider or get_provider(self.config, provider_name=provider_name)
        # Модель роли разрешается одинаково для обеих ролей (config.role_model).
        self.model = model or role_model(self.config, provider_name)

        self.base_url = (self.provider.base_url or "").strip().rstrip("/")
        self.url = f"{self.base_url}/chat/completions" if self.base_url else ""

    def _payload(
        self,
        messages: list[dict],
        *,
        temperature: float,
        output_format: str | None,
    ) -> dict:
        system_role = (
            "developer" if self.provider.compat.supports_developer_role else "system"
        )
        normalized_messages = []
        for message in messages:
            item = dict(message)
            if item.get("role") == "system":
                item["role"] = system_role
            normalized_messages.append(item)

        # Формат ответа определяется задачей, а не только настройкой провайдера:
        # классификатору нужен JSON, редактору нужен обычный Markdown-текст.
        selected_format = output_format
        if selected_format is None:
            selected_format = (
                "json_object"
                if self.provider_name == "classifier"
                and self.provider.compat.json_object_format
                else "text"
            )

        payload = {
            "model": self.model,
            "messages": normalized_messages,
            "temperature": temperature,
            "stream": False,
        }
        if self.provider.compat.disable_thinking:
            payload["think"] = False
        if selected_format == "json_object":
            payload["format"] = {"type": "json_object"}
        elif selected_format not in ("text", None):
            raise ValueError(f"Неподдерживаемый формат ответа: {selected_format}")
        return payload

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        output_format: str | None = None,
        retries: int = 2,
        retry_backoff: float = 1.5,
        timeout: float = 300.0,
        abortable: bool = True,
    ) -> ProviderCallResult:
        """Выполнить запрос с общей логикой повторов и обработки ошибок."""
        if not self.base_url:
            return ProviderCallResult.failure(
                provider_name=self.provider_name,
                model=self.model,
                url=self.url,
                error="Не указан адрес провайдера (API URL)",
            )

        try:
            payload = self._payload(
                messages,
                temperature=temperature,
                output_format=output_format,
            )
        except Exception as error:
            return ProviderCallResult.failure(
                provider_name=self.provider_name,
                model=self.model,
                url=self.url,
                error=_exception_message(error),
            )

        headers = {"Content-Type": "application/json"}
        if self.provider.api_key:
            headers["Authorization"] = f"Bearer {self.provider.api_key}"

        attempts = max(0, int(retries)) + 1
        last_error = "неизвестная ошибка"
        last_status: Optional[int] = None

        for attempt in range(attempts):
            client: httpx.Client | None = None
            registered = False
            aborted = False
            try:
                client = httpx.Client(timeout=timeout)
                if abortable:
                    with _active_lock:
                        _active_requests[id(client)] = (client, self.provider_name)
                    registered = True

                response = client.post(self.url, headers=headers, json=payload)
                if response.is_error:
                    last_status = response.status_code
                    raise _ProviderResponseError(_response_error(response))
                try:
                    data = response.json()
                except Exception as error:
                    raise _ProviderResponseError(
                        f"HTTP {response.status_code}: провайдер вернул некорректный JSON"
                    ) from error

                content = _message_content(data)
                if content is None:
                    raise _ProviderResponseError(
                        "Провайдер вернул пустой или неподдерживаемый ответ"
                    )
                return ProviderCallResult(
                    ok=True,
                    content=content,
                    error=None,
                    provider_name=self.provider_name,
                    model=self.model,
                    url=self.url,
                    attempts=attempt + 1,
                    status_code=response.status_code,
                )
            except Exception as error:  # timeout, network, HTTP or malformed response
                aborted = bool(client is not None and getattr(client, "_tg_aborted", False))
                if aborted:
                    logger.info(
                        "Запрос к модели прерван извне (роль=%s, модель=%s)",
                        self.provider_name,
                        self.model,
                    )
                    return ProviderCallResult.failure(
                        provider_name=self.provider_name,
                        model=self.model,
                        url=self.url,
                        error="Запрос к модели прерван пользователем",
                        attempts=attempt + 1,
                        aborted=True,
                        status_code=last_status,
                    )

                last_error = (
                    str(error)
                    if isinstance(error, _ProviderResponseError)
                    else _exception_message(error)
                )
                logger.warning(
                    "Ошибка обращения к модели (роль=%s, попытка %d/%d, %s): %s",
                    self.provider_name,
                    attempt + 1,
                    attempts,
                    self.url,
                    last_error,
                )
                # Таймаут не повторяем: генерация дольше лимита воспроизводится
                # и при повторе (тот же запрос — тот же результат), поэтому
                # повтор лишь тратит ещё один полный таймаут. Общее правило
                # для обеих ролей; сетевые/HTTP-ошибки повторяем как раньше.
                if isinstance(error, httpx.TimeoutException):
                    break
            finally:
                if registered and client is not None:
                    with _active_lock:
                        _active_requests.pop(id(client), None)
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass

            if attempt < attempts - 1:
                # Роль остановили (выключен переключатель) между попытками —
                # не начинаем новую: модель должна замолкнуть сразу.
                if abortable and role_stopped(self.provider_name):
                    logger.info(
                        "Роль '%s' остановлена между попытками — прерываем",
                        self.provider_name,
                    )
                    return ProviderCallResult.failure(
                        provider_name=self.provider_name,
                        model=self.model,
                        url=self.url,
                        error="Запрос к модели прерван пользователем",
                        attempts=attempt + 1,
                        aborted=True,
                        status_code=last_status,
                    )
                time.sleep(max(0.0, retry_backoff) * (attempt + 1))

        # Фактически выполнено попыток (может быть меньше `attempts`:
        # таймаут не повторяем, остановка роли прерывает цикл).
        tried = max(1, attempt + 1)
        logger.error(
            "Модель недоступна после %d попыток (роль=%s, модель=%s, %s): %s",
            tried,
            self.provider_name,
            self.model,
            self.url,
            last_error,
        )
        return ProviderCallResult.failure(
            provider_name=self.provider_name,
            model=self.model,
            url=self.url,
            error=last_error,
            attempts=tried,
            status_code=last_status,
        )


class _ProviderResponseError(RuntimeError):
    """Внутренняя ошибка ответа провайдера с уже подготовленным текстом."""


def call_role(
    role: str,
    messages: list[dict],
    *,
    temperature: float = 0.0,
    output_format: str | None = None,
    model: str | None = None,
    abortable: bool = True,
) -> ProviderCallResult:
    """Единый вызов модели для любой роли ('classifier' / 'editor').

    Одна и та же логика для обеих ролей: свой провайдер/модель из конфига,
    общие повторы/таймауты, общая фиксация последней ошибки
    (:func:`last_provider_error`) для одинаковых оповещений в UI.
    Прерывание (выключение переключателя) останавливает запрос мгновенно,
    а между попытками не даёт начать новую (см. :func:`abort_requests`).
    """
    result = ProviderClient(role, model=model).chat(
        messages,
        temperature=temperature,
        output_format=output_format,
        retries=ROLE_RETRIES,
        retry_backoff=ROLE_RETRY_BACKOFF,
        timeout=ROLE_REQUEST_TIMEOUT,
        abortable=abortable,
    )
    _last_role_errors[role] = None if result.ok else result.error
    if not result.ok and not result.aborted:
        logger.warning(
            "Модель роли '%s' недоступна (%s, модель=%s): %s",
            role,
            result.url,
            result.model,
            result.error,
        )
    return result


def _names_from_openai(data) -> list[str]:
    """Извлечь имена моделей из ответа OpenAI-совместимого /models."""
    out: list[str] = []
    items = data.get("data") if isinstance(data, dict) else data
    if isinstance(items, list):
        for m in items:
            if isinstance(m, dict):
                name = m.get("id") or m.get("name") or m.get("model")
                if name:
                    out.append(str(name))
    return out


def list_models(
    base_url: str = "", api_key: str = "", provider_name: str = "classifier"
) -> dict:
    """Запросить у провайдера список доступных моделей (общая логика для ролей).

    Если ``base_url`` не указан — берётся адрес провайдера роли, как при
    проверке соединения.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        try:
            prov = get_provider(load_config(), provider_name=provider_name)
            candidate = (prov.base_url or "").strip().rstrip("/")
            if not api_key:
                api_key = prov.api_key or ""
            base = candidate
        except Exception:
            pass
    if not base:
        return {"ok": False, "error": "Не указан адрес провайдера (API URL)"}

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    models: list[str] = []
    last_err = None

    # Определяем корневой URL для Ollama API
    ollama_root = base
    if base.endswith("/v1"):
        ollama_root = base[:-3]

    # 1) Пробуем нативный Ollama /api/tags (наиболее надёжный для Ollama)
    try:
        resp = httpx.get(f"{ollama_root}/api/tags", headers=headers, timeout=15.0)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and "models" in data:
                models = [
                    str(m["name"])
                    for m in data["models"]
                    if isinstance(m, dict) and m.get("name")
                ]
            elif isinstance(data, list):
                models = [
                    str(m["name"]) for m in data if isinstance(m, dict) and m.get("name")
                ]
    except Exception as e:
        last_err = e

    # 2) Если не вышло, пробуем OpenAI-совместимый /models
    if not models:
        try:
            resp = httpx.get(f"{base}/models", headers=headers, timeout=15.0)
            if resp.status_code == 200:
                models = _names_from_openai(resp.json())
        except Exception as e:
            if last_err is None:
                last_err = e

    models = sorted(set(filter(None, models)))
    if models:
        return {"ok": True, "models": models}

    err_msg = str(last_err) if last_err else "пусто"
    return {"ok": False, "error": f"Не удалось получить список моделей: {err_msg}"}


def test_connection(
    provider_name: str = "classifier",
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Проверить связь с провайдером/моделью роли («Проверить соединение»).

    Одна и та же логика и одинаковые оповещения для классификатора и
    редактора: используются настройки выбранной роли (при необязательных
    ``base_url``/``api_key`` — значения из формы), её системный промпт и
    общий транспорт с теми же повторами, что и при реальной обработке.
    """
    cfg = load_config()
    model = role_model(cfg, provider_name)
    provider = provider_for_overrides(
        provider_name, config=cfg, base_url=base_url, api_key=api_key
    )
    result = ProviderClient(provider_name, config=cfg, provider=provider, model=model).chat(
        [
            {"role": "system", "content": role_system_prompt(cfg, provider_name)},
            {
                "role": "user",
                "content": "Кратко подтверди, что ты на связи, одним-двумя словами.",
            },
        ],
        temperature=0.0,
        retries=ROLE_RETRIES,
        retry_backoff=ROLE_RETRY_BACKOFF,
        timeout=ROLE_REQUEST_TIMEOUT,
        abortable=False,
    )
    if result.ok:
        _last_role_errors[provider_name] = None
        return {
            "ok": True,
            "model": model,
            "reply": (result.content or "")[:200],
            "message": f"Связь установлена. Модель {model} активна.",
        }
    _last_role_errors[provider_name] = result.error
    return {
        "ok": False,
        "model": model,
        "error": result.error or "нет соединения",
    }


def provider_for_overrides(
    provider_name: str,
    *,
    config: AppConfig | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ProviderConfig:
    """Вернуть настройки роли с необязательными значениями из формы проверки."""
    cfg = config or load_config()
    provider = get_provider(cfg, provider_name=provider_name)
    updates = {}
    if base_url is not None:
        updates["base_url"] = base_url.strip()
    if api_key is not None:
        updates["api_key"] = api_key.strip()
    return provider.model_copy(update=updates) if updates else provider
