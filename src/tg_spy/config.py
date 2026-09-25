"""Конфигурация приложения (провайдер ИИ, расписание, модель).

Заменяет старый ручной мёрж dict'ов на типизированную pydantic-модель.
Конфиг читается из ``config.json`` (рядом с кодом/в /app), любые значения
можно переопределить переменными окружения. Сохраняется обратно в
``config.json`` веб-интерфейсом (без перезапуска).
"""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _default_config_path() -> str:
    """Путь к config.json: переменная окружения, затем /app, затем cwd."""
    env = os.environ.get("AGENT_CONFIG")
    if env:
        return env
    for cand in (Path("/app/config.json"), Path.cwd() / "config.json"):
        if cand.exists():
            return str(cand)
    return str(Path.cwd() / "config.json")


CONFIG_PATH = _default_config_path()


class ProviderCompat(BaseModel):
    """Особенности конкретного провайдера/модели (флаги совместимости)."""

    supports_developer_role: bool = False
    json_object_format: bool = False
    disable_thinking: bool = False


class ProviderConfig(BaseModel):
    """OpenAI-совместимый провайдер (Ollama и т.п.)."""

    base_url: str = "http://host.containers.internal:11434/v1"
    api: str = "openai-completions"
    api_key: str = "ollama"
    compat: ProviderCompat = Field(default_factory=ProviderCompat)


class ScheduleConfig(BaseModel):
    enabled: bool = True
    feed_refresh_minutes: int = 60
    topic_minutes: int = 1440


class AppConfig(BaseModel):
    """Итоговый конфиг приложения."""

    provider: str = "ollama"
    model: str = "qwen3:4b"
    timezone: str = ""  # IANA-зона для отображения времени; "" = локальное время браузера
    system_prompt: str = (
        "Ты — строгий фильтр новостей. Твоя задача — решить, относится ли "
        "каждый пост из списка к заданной теме. Отвечай только JSON, "
        "без пояснений и аналитики."
    )
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    # --- Сериализация под формат, ожидаемый фронтендом/старым кодом ---
    def to_legacy_dict(self) -> dict:
        """Словарь в форме, совместимой с веб-интерфейсом и старыми вызовами."""
        d = self.model_dump()
        # Переводим camelCase-ключи compat в то, что ждёт фронтенд.
        out_providers = {}
        for name, p in d["providers"].items():
            compat = p["compat"]
            out_providers[name] = {
                "baseUrl": p["base_url"],
                "api": p["api"],
                "apiKey": p["api_key"],
                "compat": {
                    "supportsDeveloperRole": compat["supports_developer_role"],
                    "jsonObjectFormat": compat["json_object_format"],
                    "disableThinking": compat["disable_thinking"],
                },
            }
        return {
            "provider": d["provider"],
            "model": d["model"],
            "editorModel": d.get("editor_model", ""),
            "timezone": d.get("timezone", ""),
            "systemPrompt": d["system_prompt"],
            "schedule": {
                "enabled": d["schedule"]["enabled"],
                "feedRefreshMinutes": d["schedule"]["feed_refresh_minutes"],
                "topicMinutes": d["schedule"]["topic_minutes"],
            },
            "providers": out_providers,
        }

    @classmethod
    def from_legacy_dict(cls, data: dict) -> "AppConfig":
        """Собрать модель из словаря config.json (camelCase-ключи)."""
        providers = {}
        for name, p in (data.get("providers") or {}).items():
            compat = (p or {}).get("compat") or {}
            providers[name] = ProviderConfig(
                base_url=p.get("baseUrl", "http://host.containers.internal:11434/v1"),
                api=p.get("api", "openai-completions"),
                api_key=p.get("apiKey", "ollama"),
                compat=ProviderCompat(
                    supports_developer_role=bool(compat.get("supportsDeveloperRole")),
                    json_object_format=bool(compat.get("jsonObjectFormat")),
                    disable_thinking=bool(compat.get("disableThinking")),
                ),
            )
        sched = data.get("schedule") or {}
        return cls(
            provider=data.get("provider", "ollama"),
            model=data.get("model", "qwen3:4b"),
            editor_model=data.get("editorModel", "") or data.get("editor_model", ""),
            timezone=data.get("timezone", ""),
            system_prompt=data.get(
                "systemPrompt",
                "Ты — строгий фильтр новостей. Твоя задача — решить, относится ли "
                "каждый пост из списка к заданной теме. Отвечай только JSON, "
                "без пояснений и аналитики.",
            ),
            schedule=ScheduleConfig(
                enabled=bool(sched.get("enabled", True)),
                feed_refresh_minutes=int(sched.get("feedRefreshMinutes", 60)),
                topic_minutes=int(sched.get("topicMinutes", 1440)),
            ),
            providers=providers,
        )


# Дефолтный провайдер Ollama (слабая локальная модель).
DEFAULT_PROVIDERS = {
    "ollama": ProviderConfig(
        base_url="http://host.containers.internal:11434/v1",
        api="openai-completions",
        api_key="ollama",
        compat=ProviderCompat(disable_thinking=True),
    )
}


def load_config() -> AppConfig:
    """Собрать конфиг: дефолт + config.json + переменные окружения."""
    cfg = AppConfig(providers=copy.deepcopy(DEFAULT_PROVIDERS))
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            user_cfg = AppConfig.from_legacy_dict(user)
            # Сливаем провайдеров: дефолтные + из файла.
            merged_providers = copy.deepcopy(DEFAULT_PROVIDERS)
            merged_providers.update(user_cfg.providers)
            cfg = user_cfg
            cfg.providers = merged_providers
    except FileNotFoundError:
        logger.info("config.json не найден, используется конфиг по умолчанию")
    except Exception as e:
        logger.warning("Не удалось прочитать config.json: %s", e)

    # Переопределения через переменные окружения.
    if os.environ.get("AGENT_PROVIDER"):
        cfg.provider = os.environ["AGENT_PROVIDER"]
    if os.environ.get("AGENT_MODEL"):
        cfg.model = os.environ["AGENT_MODEL"]
    if os.environ.get("AGENT_SYSTEM_PROMPT"):
        cfg.system_prompt = os.environ["AGENT_SYSTEM_PROMPT"]

    sched = cfg.schedule
    env_enabled = os.environ.get("AGENT_SCHEDULE_ENABLED")
    if env_enabled is not None:
        sched.enabled = env_enabled.strip().lower() in ("1", "true", "yes", "on")
    if os.environ.get("AGENT_FEED_REFRESH_MINUTES"):
        try:
            sched.feed_refresh_minutes = max(1, int(os.environ["AGENT_FEED_REFRESH_MINUTES"]))
        except ValueError:
            pass
    if os.environ.get("AGENT_TOPIC_MINUTES"):
        try:
            sched.topic_minutes = max(1, int(os.environ["AGENT_TOPIC_MINUTES"]))
        except ValueError:
            pass

    # Провайдер выбранный — подставим дефолтный ollama, если не описан.
    prov = cfg.providers.get(cfg.provider)
    if prov is None:
        cfg.provider = "ollama"
        prov = cfg.providers.get("ollama", DEFAULT_PROVIDERS["ollama"])

    if os.environ.get("AGENT_BASE_URL"):
        prov.base_url = os.environ["AGENT_BASE_URL"]
    if os.environ.get("AGENT_API_KEY"):
        prov.api_key = os.environ["AGENT_API_KEY"]
    return cfg


def get_provider(cfg: AppConfig | None = None) -> ProviderConfig:
    cfg = cfg or load_config()
    return cfg.providers.get(cfg.provider, DEFAULT_PROVIDERS["ollama"])


def get_config_path() -> str:
    """Путь к файлу config.json (рядом с кодом)."""
    return CONFIG_PATH


def save_config(cfg: AppConfig) -> None:
    """Сохранить конфиг провайдера/агента в config.json.

    Вызывается из веб-интерфейса (карточка настроек провайдера).
    load_config() перечитывает файл при каждом обращении, поэтому
    перезапуск не нужен.
    """
    path = CONFIG_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg.to_legacy_dict(), f, ensure_ascii=False, indent=2)
