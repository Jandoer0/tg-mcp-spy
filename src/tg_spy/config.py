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

    # Полные настройки классификатора
    classifier: ProviderConfig = Field(default_factory=lambda: ProviderConfig(
        base_url="http://host.containers.internal:11434/v1",
        api_key="ollama",
        compat=ProviderCompat(disable_thinking=True)
    ))
    classifier_model: str = "qwen3:4b"
    
    # Полные настройки редактора
    editor: ProviderConfig = Field(default_factory=lambda: ProviderConfig(
        base_url="http://host.containers.internal:11434/v1",
        api_key="ollama",
        compat=ProviderCompat(disable_thinking=True)
    ))
    editor_model: str = "qwen3:4b"

    timezone: str = ""  # IANA-зона для отображения времени; "" = локальное время браузера
    system_prompt: str = (
        "Ты — строгий фильтр новостей. Твоя задача — решить, относится ли "
        "каждый пост из списка к заданной теме. Отвечай только JSON, "
        "без пояснений и аналитики."
    )
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    # Глобальные провайдеры больше не нужны как единственный источник истины, 
    # но оставим для совместимости с API списка моделей.
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    # --- Сериализация под формат, ожидаемый фронтендом ---
    def to_legacy_dict(self) -> dict:
        """Словарь в форме, совместимой с веб-интерфейсом."""
        d = self.model_dump()
        
        def prov_to_dict(p):
            compat = p["compat"]
            return {
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
            "classifier": {
                "provider": prov_to_dict(d["classifier"]),
                "model": d["classifier_model"],
            },
            "editor": {
                "provider": prov_to_dict(d["editor"]),
                "model": d["editor_model"],
            },
            "timezone": d["timezone"],
            "systemPrompt": d["system_prompt"],
            "schedule": {
                "enabled": d["schedule"]["enabled"],
                "feedRefreshMinutes": d["schedule"]["feed_refresh_minutes"],
                "topicMinutes": d["schedule"]["topic_minutes"],
            },
            "providers": {name: prov_to_dict(p) for name, p in d["providers"].items()},
        }

    @classmethod
    def from_legacy_dict(cls, data: dict) -> "AppConfig":
        """Собрать модель из словаря config.json."""
        
        def dict_to_prov(p):
            if not p: return ProviderConfig()
            compat = (p or {}).get("compat") or {}
            return ProviderConfig(
                base_url=p.get("baseUrl", "http://host.containers.internal:11434/v1"),
                api=p.get("api", "openai-completions"),
                api_key=p.get("apiKey", "ollama"),
                compat=ProviderCompat(
                    supports_developer_role=bool(compat.get("supportsDeveloperRole")),
                    json_object_format=bool(compat.get("jsonObjectFormat")),
                    disable_thinking=bool(compat.get("disableThinking")),
                ),
            )

        providers = {}
        for name, p in (data.get("providers") or {}).items():
            providers[name] = dict_to_prov(p)
        
        classifier_data = data.get("classifier") or {}
        editor_data = data.get("editor") or {}
        
        sched = data.get("schedule") or {}
        return cls(
            classifier=dict_to_prov(classifier_data.get("provider")),
            classifier_model=classifier_data.get("model", "qwen3:4b"),
            editor=dict_to_prov(editor_data.get("provider")),
            editor_model=editor_data.get("model", "qwen3:4b"),
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
    cfg = AppConfig()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            user_cfg = AppConfig.from_legacy_dict(user)
            cfg = user_cfg
    except FileNotFoundError:
        logger.info("config.json не найден, используется конфиг по умолчанию")
    except Exception as e:
        logger.warning("Не удалось прочитать config.json: %s", e)

    # Переопределения через переменные окружения.
    # Классификатор
    if os.environ.get("AGENT_CLASSIFIER_PROVIDER_URL"):
        cfg.classifier.base_url = os.environ["AGENT_CLASSIFIER_PROVIDER_URL"]
    if os.environ.get("AGENT_CLASSIFIER_API_KEY"):
        cfg.classifier.api_key = os.environ["AGENT_CLASSIFIER_API_KEY"]
    if os.environ.get("AGENT_CLASSIFIER_MODEL"):
        cfg.classifier_model = os.environ["AGENT_CLASSIFIER_MODEL"]
    
    # Редактор
    if os.environ.get("AGENT_EDITOR_PROVIDER_URL"):
        cfg.editor.base_url = os.environ["AGENT_EDITOR_PROVIDER_URL"]
    if os.environ.get("AGENT_EDITOR_API_KEY"):
        cfg.editor.api_key = os.environ["AGENT_EDITOR_API_KEY"]
    if os.environ.get("AGENT_EDITOR_MODEL"):
        cfg.editor_model = os.environ["AGENT_EDITOR_MODEL"]

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

    return cfg


def get_provider(cfg: AppConfig | None = None, provider_name: str | None = None) -> ProviderConfig:
    """Получить конфигурацию провайдера.
    Если provider_name == 'classifier', возвращаем настройки классификатора.
    Если 'editor' — редактора. 
    Если None — по умолчанию классификатора.
    """
    cfg = cfg or load_config()
    if provider_name == "editor":
        return cfg.editor
    return cfg.classifier


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
