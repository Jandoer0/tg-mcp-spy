"""Тесты конфигурации: раздельные провайдеры ролей и симметрия структур."""

from mcp_news.config import AppConfig, get_provider, load_config, save_config


def test_defaults():
    # Чистые дефолты (без config.json/env): у обеих ролей симметричные структуры.
    cfg = AppConfig()
    assert cfg.classifier.model == "qwen3:4b"
    assert cfg.editor.model == "qwen3:4b"
    assert cfg.classifier.provider.base_url
    assert cfg.editor.provider.base_url


def test_env_override(monkeypatch):
    # env переопределяет модель каждой роли независимо.
    monkeypatch.setenv("AGENT_CLASSIFIER_MODEL", "llama3.2")
    monkeypatch.setenv("AGENT_EDITOR_MODEL", "gpt-4o-mini")
    cfg = load_config()
    assert cfg.classifier.model == "llama3.2"
    assert cfg.editor.model == "gpt-4o-mini"


def test_independent_providers(monkeypatch):
    # Классификатор — локальная модель, редактор — облачный провайдер:
    # две независимые конфигурации, одинаковая структура.
    monkeypatch.setenv("AGENT_CLASSIFIER_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("AGENT_EDITOR_URL", "https://api.example.com/v1")
    monkeypatch.setenv("AGENT_EDITOR_KEY", "sk-secret")
    cfg = load_config()
    assert get_provider(cfg, "classifier").base_url == "http://127.0.0.1:11434/v1"
    assert get_provider(cfg, "editor").base_url == "https://api.example.com/v1"
    assert get_provider(cfg, "editor").api_key == "sk-secret"


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CONFIG", str(tmp_path / "config.json"))
    # Убираем env-оверрайды провайдеров из conftest — проверяем чистый
    # roundtrip через config.json (приоритет при загрузке: ENV > файл).
    for var in (
        "AGENT_CLASSIFIER_URL", "AGENT_CLASSIFIER_KEY", "AGENT_CLASSIFIER_MODEL",
        "AGENT_EDITOR_URL", "AGENT_EDITOR_KEY", "AGENT_EDITOR_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = load_config()
    cfg.classifier.model = "my-local-model"
    cfg.editor.model = "my-cloud-model"
    cfg.editor.provider.base_url = "https://api.example.com/v1"
    cfg.schedule.feed_refresh_minutes = 30
    save_config(cfg)

    reloaded = load_config()
    assert reloaded.classifier.model == "my-local-model"
    assert reloaded.editor.model == "my-cloud-model"
    assert reloaded.editor.provider.base_url == "https://api.example.com/v1"
    assert reloaded.schedule.feed_refresh_minutes == 30
    # Формат на диске — legacy-словарь с вложенными provider/model у обеих ролей.
    data = reloaded.to_legacy_dict()
    assert data["classifier"]["model"] == "my-local-model"
    assert data["editor"]["model"] == "my-cloud-model"
    assert data["editor"]["provider"]["baseUrl"] == "https://api.example.com/v1"


def test_from_legacy_dict():
    legacy = {
        "classifier": {
            "provider": {"baseUrl": "http://h:11434/v1", "apiKey": "k"},
            "model": "c-model",
        },
        "editor": {
            "provider": {"baseUrl": "https://cloud/v1", "apiKey": "ck"},
            "model": "e-model",
        },
        "providers": {
            "ollama": {
                "baseUrl": "http://h:11434/v1",
                "apiKey": "k",
                "compat": {"disableThinking": True},
            }
        },
    }
    cfg = AppConfig.from_legacy_dict(legacy)
    assert cfg.classifier.provider.base_url == "http://h:11434/v1"
    assert cfg.classifier.model == "c-model"
    assert cfg.editor.provider.base_url == "https://cloud/v1"
    assert cfg.editor.model == "e-model"
    assert cfg.providers["ollama"].compat.disable_thinking is True


def test_from_legacy_flat_roles():
    # Старый формат: плоские провайдеры + отдельные поля *_model.
    legacy = {
        "classifier": {"baseUrl": "http://h:11434/v1"},
        "classifier_model": "old-c",
        "editor": {"baseUrl": "https://old/v1", "apiKey": "k"},
        "editor_model": "old-e",
    }
    cfg = AppConfig.from_legacy_dict(legacy)
    assert cfg.classifier.provider.base_url == "http://h:11434/v1"
    assert cfg.classifier.model == "old-c"
    assert cfg.editor.provider.base_url == "https://old/v1"
    assert cfg.editor.model == "old-e"
