"""Конфигурация локального ИИ-агента и провайдера (по умолчанию Ollama).

Конфигурация читается из ``config.json`` (рядом с этим файлом), любые
значения можно переопределить переменными окружения. Дефолтный провайдер —
слабая локальная модель через Ollama (OpenAI-совместимый эндпоинт
``/v1/chat/completions``).
"""
import copy
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = os.environ.get("AGENT_CONFIG", str(Path(__file__).parent / "config.json"))

# Дефолтный конфиг провайдера (Ollama, локальная слабая модель).
DEFAULT_CONFIG = {
    "provider": "ollama",
    "model": "qwen3:4b",
    "systemPrompt": (
        "Ты — строгий фильтр новостей. Твоя задача — решить, относится ли "
        "каждый пост из списка к заданной теме. Отвечай только JSON, "
        "без пояснений и аналитики."
    ),
    "schedule": {
        "enabled": True,
        "feedRefreshMinutes": 60,  # авто-обновление ленты (мин)
        "topicMinutes": 1440,      # периодичность запуска агента по теме (мин, раз в сутки)
    },
    "providers": {
        "ollama": {
            "baseUrl": "http://host.containers.internal:11434/v1",
            "api": "openai-completions",
            "apiKey": "ollama",
            "compat": {
                "supportsDeveloperRole": False,
                "supportsReasoningEffort": False,
                # Ollama через openai-compat умеет форсировать JSON-ответ.
                "jsonObjectFormat": True,
                # Отключает рассуждения (CoT) для моделей вроде Qwen3 —
                # иначе они «думают» десятки секунд. Включается в config.json
                # под конкретную модель; здесь по умолчанию выключено.
                "disableThinking": True,  # qwen3 — рассуждающая модель
            },
        }
    },
}


def load_config() -> dict:
    """Собрать итоговый конфиг: дефолт + config.json + переменные окружения."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = __import__("json").load(f)
        if isinstance(user, dict):
            for k, v in user.items():
                if k == "providers" and isinstance(v, dict):
                    cfg["providers"].update(v)
                else:
                    cfg[k] = v
    except FileNotFoundError:
        logger.info("config.json не найден, используется конфиг по умолчанию")
    except Exception as e:
        logger.warning("Не удалось прочитать config.json: %s", e)

    # Переопределения через переменные окружения
    if os.environ.get("AGENT_PROVIDER"):
        cfg["provider"] = os.environ["AGENT_PROVIDER"]
    if os.environ.get("AGENT_MODEL"):
        cfg["model"] = os.environ["AGENT_MODEL"]
    if os.environ.get("AGENT_SYSTEM_PROMPT"):
        cfg["systemPrompt"] = os.environ["AGENT_SYSTEM_PROMPT"]

    sched = cfg.setdefault("schedule", {})
    env_enabled = os.environ.get("AGENT_SCHEDULE_ENABLED")
    if env_enabled is not None:
        sched["enabled"] = env_enabled.strip().lower() in ("1", "true", "yes", "on")
    if os.environ.get("AGENT_FEED_REFRESH_MINUTES"):
        try:
            sched["feedRefreshMinutes"] = max(1, int(os.environ["AGENT_FEED_REFRESH_MINUTES"]))
        except ValueError:
            pass
    if os.environ.get("AGENT_TOPIC_MINUTES"):
        try:
            sched["topicMinutes"] = max(1, int(os.environ["AGENT_TOPIC_MINUTES"]))
        except ValueError:
            pass

    # Провайдер выбранный — подставим дефолтный ollama, если не описан.
    provider_name = cfg.get("provider", "ollama")
    prov = cfg["providers"].get(provider_name)
    if prov is None:
        prov = cfg["providers"].get("ollama", {})
        cfg["provider"] = "ollama"

    if os.environ.get("AGENT_BASE_URL"):
        prov["baseUrl"] = os.environ["AGENT_BASE_URL"]
    if os.environ.get("AGENT_API_KEY"):
        prov["apiKey"] = os.environ["AGENT_API_KEY"]

    return cfg


def get_provider(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    return cfg.get("providers", {}).get(cfg.get("provider", "ollama"), {})


def get_config_path() -> str:
    """Путь к файлу config.json (рядом с кодом)."""
    return CONFIG_PATH


def save_config(cfg: dict) -> None:
    """Сохранить конфиг провайдера/агента в config.json.

    Вызывается из веб-интерфейса (карточка настроек провайдера). load_config()
    перечитывает файл при каждом обращении, поэтому перезапуск не нужен.
    """
    path = CONFIG_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        __import__("json").dump(cfg, f, ensure_ascii=False, indent=2)
