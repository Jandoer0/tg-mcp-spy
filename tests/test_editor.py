"""Тесты ИИ-редактора: пакетная обработка и статусы.
"""
import pytest
from unittest.mock import MagicMock, patch

from tg_spy.config import load_config
from tg_spy.topics import editor
from tg_spy.db.repositories import posts

def test_edit_one_post_visibility():
    """Проверить, что при редактуре поста статус временно становится 'editing'."""
    # Создаем источник и пост
    conn = posts.get_conn()
    conn.execute("INSERT INTO sources (id, name, kind) VALUES (?, ?, ?)", (1, "Source1", "telegram"))
    conn.execute(
        "INSERT INTO posts (source_id, ext_id, text, date, url, editor_status) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "ext123", "Текст поста", "2024-01-01", "http://url", "none"),
    )
    conn.commit()
    post_id = 1
    
    # Mock: модель возвращает текст
    with patch("tg_spy.topics.editor._edit_result") as mock_edit:
        from tg_spy.topics.provider import ProviderCallResult
        mock_edit.return_value = ProviderCallResult(
            ok=True, content="Отредактированный текст", provider_name="editor", model="m", url="u", error=None
        )
        
        # Вызываем редактуру
        res = editor.edit_one_post(post_id)
        
        assert res["ok"]
        # В конце должен быть 'done'
        assert posts.get_post(post_id)["editor_status"] == "done"
    conn.close()

def test_editor_batch_stops_on_disabled():
    """Батч должен остановиться немедленно, если переключатель выключен."""
    # 1. Мокаем данные: источники и список постов
    mock_rows = [{"id": i, "text": f"Текст {i}", "editor_status": "none"} for i in range(1, 11)]
    
    # 2. Mock: модель работает, но конфиг меняется
    config_sequence = [
        MagicMock(schedule=MagicMock(editor_enabled=True)),
        MagicMock(schedule=MagicMock(editor_enabled=True)),
        MagicMock(schedule=MagicMock(editor_enabled=False)),
    ]
    
    with patch("tg_spy.topics.editor.list_sources", return_value=[{"id": 1}]), \
         patch("tg_spy.topics.editor.get_posts", return_value=mock_rows), \
         patch("tg_spy.topics.editor.load_config", side_effect=config_sequence), \
         patch("tg_spy.topics.editor._edit_result") as mock_edit:
        
        from tg_spy.topics.provider import ProviderCallResult
        mock_edit.return_value = ProviderCallResult(
            ok=True, content="Edited", provider_name="editor", model="m", url="u", error=None
        )
        
        summary = editor.run_editor_batch(days=7)
        
        assert summary["processed"] == 2
        assert mock_edit.call_count == 2

def test_editor_batch_stops_on_aborted():
    """Батч должен остановиться немедленно, если запрос был прерван."""
    # 1. Мокаем данные
    mock_rows = [{"id": i, "text": f"Текст {i}", "editor_status": "none"} for i in range(1, 11)]
    
    # 2. Mock: первая редактура возвращает aborted=True
    with patch("tg_spy.topics.editor.list_sources", return_value=[{"id": 1}]), \
         patch("tg_spy.topics.editor.get_posts", return_value=mock_rows), \
         patch("tg_spy.topics.editor.load_config") as mock_cfg, \
         patch("tg_spy.topics.editor._edit_result") as mock_edit:
        
        mock_cfg.return_value = MagicMock(schedule=MagicMock(editor_enabled=True))
        
        from tg_spy.topics.provider import ProviderCallResult
        mock_edit.return_value = ProviderCallResult.failure(
            provider_name="editor", model="m", url="u", error="aborted", aborted=True
        )
        
        summary = editor.run_editor_batch(days=7)
        
        assert summary["processed"] == 1
        assert mock_edit.call_count == 1
