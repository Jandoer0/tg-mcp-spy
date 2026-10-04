"""Конфигурация приложения (провайдер ИИ, расписание, модель).

Заменяет старый ручной мёрж dict'ов на типизированную pydantic-модель.
Конфиг читается из ``config.json`` (рядом с кодом/в /app), любые значения
можно переопределить переменными окружения. Сохраняется обратно в
``config.json`` веб-интерфейсом (без перезапуска).
"""
from __future__ import annotations

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
    # ИИ-редактор: включён ли периодический запуск редактора (взаимоисключающе
    # с классификатором — одновременно активен только один переключатель).
    editor_enabled: bool = False
    # Период периодического запуска ИИ-редактора (мин).
    editor_minutes: int = 1440


class ClassifierConfig(BaseModel):
    """Конфигурация классификатора с флагом включения."""
    provider: ProviderConfig = Field(default_factory=lambda: ProviderConfig(
        base_url="http://host.containers.internal:11434/v1",
        api_key="ollama",
        compat=ProviderCompat(disable_thinking=True)
    ))
    model: str = "qwen3:4b"
    enabled: bool = True


class EditorConfig(BaseModel):
    """Конфигурация ИИ-редактора — симметрична классификатору.

    Свой провайдер и своя модель: пользователь может, например, держать
    классификатор на локальной Ollama, а редактор — у облачного провайдера.
    Логика работы с провайдером при этом общая (topics.provider).
    """
    provider: ProviderConfig = Field(default_factory=lambda: ProviderConfig(
        base_url="http://host.containers.internal:11434/v1",
        api_key="ollama",
        compat=ProviderCompat(disable_thinking=True)
    ))
    model: str = "qwen3:4b"


# Дефолтный системный промпт ИИ-редактора (редактируется в интерфейсе).
EDITOR_SYSTEM_PROMPT_DEFAULT = """Ты — редактор новостной ленты. Твоя задача — оформить пост минимальной разметкой Markdown, не меняя его смысл, факты и примерно тот же объём.

Что делать с содержимым:
1. По сути оставь текст без изменений. Убери только явный мусор: призывы подписаться/лайкнуть/перейти («Подпишись», «Больше новостей на…», «@channel», «Жми колокольчик») и подряд повторяющиеся строки.
2. Не удаляй названия медиа/каналов/сайтов как указание источника («— iPhones.ru», «Источник: Meduza»). Декоративные эмодзи убирай (смысловые — флаги, валюты — оставляй). Лишние пустые строки своди к одной между абзацами.

ОБЯЗАТЕЛЬНОЕ ОФОРМЛЕНИЕ (это и есть задача — примени разметку к исходному тексту):
- Если в начале поста есть заголовок или анонс — оберни его в **жирный** шрифт: **заголовок**.
- В длинных постах (от ~5 строк) выдели **жирным** одну-две самые важные фразы, передающие главную мысль (без пересказа).
- Ссылки и упоминания-ссылки вида @канал или название сайта-источника, если они являются ссылками, оформляй как Markdown-ссылку [текст](url). Не придумывай ссылок, если их нет в тексте.
- Не добавляй новых абзацев, подзаголовков и никаких пояснений.

Верни ТОЛЬКО отформатированный текст поста. Без вступлений, комментариев и заключений."""


class AppConfig(BaseModel):
    """Итоговый конфиг приложения."""

    # Полные настройки классификатора
    classifier: ClassifierConfig = Field(default_factory=ClassifierConfig)
    
    # Полные настройки редактора (симметрично классификатору)
    editor: EditorConfig = Field(default_factory=EditorConfig)

    timezone: str = ""  # IANA-зона для отображения времени; "" = локальное время браузера
    system_prompt: str = (
        "Ты — строгий фильтр новостей. Твоя задача — решить, относится ли "
        "каждый пост из списка к заданной теме. Отвечай только JSON, "
        "без пояснений и аналитики."
    )
    # Системный промпт ИИ-редактора (редактируется в интерфейсе).
    editor_system_prompt: str = EDITOR_SYSTEM_PROMPT_DEFAULT
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

        classifier = d["classifier"]
        # Поддержка старой и новой структуры классификатора
        if "provider" in classifier:
             # Новая структура ClassifierConfig
             c_prov = classifier["provider"]
             c_model = classifier["model"]
             c_enabled = classifier.get("enabled", True)
        else:
             # Старая структура (если вдруг осталась)
             c_prov = classifier
             c_model = d.get("classifier_model", "qwen3:4b")
             c_enabled = True

        return {
            "classifier": {
                "provider": prov_to_dict(c_prov),
                "model": c_model,
                "enabled": c_enabled,
            },
            "editor": {
                "provider": prov_to_dict(d["editor"]["provider"]),
                "model": d["editor"]["model"],
            },
            "timezone": d["timezone"],
            "systemPrompt": d["system_prompt"],
            "editorSystemPrompt": d["editor_system_prompt"],
            "schedule": {
                "enabled": d["schedule"]["enabled"],
                "feedRefreshMinutes": d["schedule"]["feed_refresh_minutes"],
                "topicMinutes": d["schedule"]["topic_minutes"],
                "editorEnabled": d["schedule"]["editor_enabled"],
                "editorMinutes": d["schedule"]["editor_minutes"],
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
        
        # Обработка классификатора (поддержка старой и новой структуры)
        if "provider" in classifier_data:
            # Новая структура с вложенным provider
            c_provider = dict_to_prov(classifier_data.get("provider"))
            c_model = classifier_data.get("model", "qwen3:4b")
            c_enabled = classifier_data.get("enabled", True)
            classifier_cfg = ClassifierConfig(provider=c_provider, model=c_model, enabled=c_enabled)
        else:
            # Старая структура (плоская)
            c_provider = dict_to_prov(classifier_data)
            c_model = data.get("classifier_model", "qwen3:4b")
            classifier_cfg = ClassifierConfig(provider=c_provider, model=c_model, enabled=True)

        # Обработка редактора — симметрично классификатору (вложенный provider)
        if "provider" in editor_data:
            e_provider = dict_to_prov(editor_data.get("provider"))
            e_model = editor_data.get("model", "qwen3:4b")
        else:
            # Старая структура (плоская) + старое поле editor_model
            e_provider = dict_to_prov(editor_data)
            e_model = data.get("editor_model", editor_data.get("model", "qwen3:4b"))
        editor_cfg = EditorConfig(provider=e_provider, model=e_model)
        
        sched = data.get("schedule") or {}
        return cls(
            classifier=classifier_cfg,
            editor=editor_cfg,
            timezone=data.get("timezone", ""),
            system_prompt=data.get(
                "systemPrompt",
                "Ты — строгий фильтр новостей. Твоя задача — решить, относится ли "
                "каждый пост из списка к заданной теме. Отвечай только JSON, "
                "без пояснений и аналитики.",
            ),
            editor_system_prompt=data.get("editorSystemPrompt", EDITOR_SYSTEM_PROMPT_DEFAULT),
            schedule=ScheduleConfig(
                enabled=bool(sched.get("enabled", True)),
                feed_refresh_minutes=int(sched.get("feedRefreshMinutes", 60)),
                topic_minutes=int(sched.get("topicMinutes", 1440)),
                editor_enabled=bool(sched.get("editorEnabled", False)),
                editor_minutes=int(sched.get("editorMinutes", 1440)),
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
    """Собрать конфиг: дефолт -> config.json -> переменные окружения.
    
    Приоритет: ENV > config.json > Default.
    """
    # 1. Начинаем с дефолтов
    cfg = AppConfig()
    
    # 2. Накладываем config.json, если он есть
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            # from_legacy_dict уже применил дефолты к значениям из файла —
            # используем результат как итоговый конфиг.
            cfg = AppConfig.from_legacy_dict(user)
    except FileNotFoundError:
        logger.info("config.json не найден, используются значения по умолчанию")
    except Exception as e:
        logger.warning("Не удалось прочитать config.json: %s", e)

    # 3. Переопределяем через переменные окружения (самый высокий приоритет)
    # Классификатор
    if os.environ.get("AGENT_CLASSIFIER_URL"):
        cfg.classifier.provider.base_url = os.environ["AGENT_CLASSIFIER_URL"]
    if os.environ.get("AGENT_CLASSIFIER_KEY"):
        cfg.classifier.provider.api_key = os.environ["AGENT_CLASSIFIER_KEY"]
    if os.environ.get("AGENT_CLASSIFIER_MODEL"):
        cfg.classifier.model = os.environ["AGENT_CLASSIFIER_MODEL"]
    
    # Редактор (своя конфигурация провайдера/модели — как у классификатора)
    if os.environ.get("AGENT_EDITOR_URL"):
        cfg.editor.provider.base_url = os.environ["AGENT_EDITOR_URL"]
    if os.environ.get("AGENT_EDITOR_KEY"):
        cfg.editor.provider.api_key = os.environ["AGENT_EDITOR_KEY"]
    if os.environ.get("AGENT_EDITOR_MODEL"):
        cfg.editor.model = os.environ["AGENT_EDITOR_MODEL"]

    if os.environ.get("AGENT_TIMEZONE"):
        cfg.timezone = os.environ["AGENT_TIMEZONE"]

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
        return cfg.editor.provider
    # У классификатора провайдер вложен в cfg.classifier.provider
    # (cfg.classifier — это ClassifierConfig, а не ProviderConfig).
    return cfg.classifier.provider


def role_model(cfg: AppConfig | None = None, role: str = "classifier") -> str:
    """Модель роли (одинаковые правила для классификатора и редактора)."""
    cfg = cfg or load_config()
    if role == "editor":
        return cfg.editor.model or "llama3.2"
    return cfg.classifier.model or "llama3.2"


def role_system_prompt(cfg: AppConfig | None = None, role: str = "classifier") -> str:
    """Системный промпт роли (у каждой роли свой, хранится в конфиге)."""
    cfg = cfg or load_config()
    if role == "editor":
        return cfg.editor_system_prompt
    return cfg.system_prompt


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
