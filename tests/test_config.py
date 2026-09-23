"""Тесты конфигурации (pydantic) и слоя БД."""
import os

from tg_spy.config import AppConfig, load_config, save_config


def test_defaults():
    cfg = load_config()
    assert cfg.model == "qwen3:4b"
    assert cfg.provider == "ollama"
    assert cfg.providers["ollama"].base_url


def test_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "llama3.2")
    cfg = load_config()
    assert cfg.model == "llama3.2"


def test_save_load_roundtrip():
    cfg = load_config()
    cfg.model = "my-model"
    cfg.schedule.feed_refresh_minutes = 30
    cfg.providers["ollama"].compat.disable_thinking = False
    save_config(cfg)

    reloaded = load_config()
    assert reloaded.model == "my-model"
    assert reloaded.schedule.feed_refresh_minutes == 30
    assert reloaded.to_legacy_dict()["providers"]["ollama"]["compat"][
        "disableThinking"
    ] is False


def test_from_legacy_dict():
    legacy = {
        "provider": "ollama",
        "model": "x",
        "providers": {
            "ollama": {
                "baseUrl": "http://h:11434/v1",
                "apiKey": "k",
                "compat": {"disableThinking": True},
            }
        },
    }
    cfg = AppConfig.from_legacy_dict(legacy)
    assert cfg.providers["ollama"].base_url == "http://h:11434/v1"
    assert cfg.providers["ollama"].compat.disable_thinking is True
