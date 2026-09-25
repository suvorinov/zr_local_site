"""Общие фикстуры pytest.

Каждый тест изолирован от боевых данных: БД создаётся во временном
каталоге, CSRF-секрет и кэши погоды/новостей перенаправляются в tmp.
"""

import pytest

import app.db as db_module
import app.csrf as csrf_module
import app.feed as feed_module
import app.weather as weather_module
from app.config import Settings


def make_settings(**overrides) -> Settings:
    """Создаёт настройки с безопасными значениями по умолчанию."""
    base = {
        "admin_username": "testadmin",
        "admin_password": "testpass123",
        "timezone": "Europe/Moscow",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Изолирует БД, CSRF-секрет и файловые кэши от реальных данных."""
    db_file = tmp_path / "test.db"
    real_get_connection = db_module.get_connection

    def fake_get_connection(db_path=None):
        return real_get_connection(db_file)

    monkeypatch.setattr(db_module, "get_connection", fake_get_connection)
    db_module.init_db()

    monkeypatch.setattr(csrf_module, "_signing_key", "test-signing-key")

    monkeypatch.setattr(weather_module, "_CACHE_PATH", tmp_path / "weather_cache.json")
    monkeypatch.setattr(feed_module, "_CACHE_PATH", tmp_path / "news_cache.json")

    return tmp_path