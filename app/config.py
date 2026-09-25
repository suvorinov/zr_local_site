"""Конфигурация приложения.

Содержит настройки путей, базы данных и параметров генерации.
"""

import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения.

    Attributes:
        db_path: Путь к файлу SQLite базы данных.
        app_title: Название приложения.
        background_dir: Путь к каталогу с фоновыми изображениями.
        greeting_dir: Путь к каталогу для сгенерированных поздравлений.
        rotation_seconds: Интервал ротации поздравлений в секундах.
        empty_rotation_seconds: Интервал ротации инфо-блоков, когда именинников нет.
        check_time: Время проверки дней рождений (ЧЧ:ММ).
        timezone: Часовой пояс приложения (IANA, например Europe/Moscow).
        ticker_speed: Скорость бегущей строки (пикселей в секунду).
        admin_username: Логин администратора (обязательно задать в .env).
        admin_password: Пароль администратора (задать ИЛИ хэш).
        admin_password_hash: bcrypt-хэш пароля администратора (альтернатива).
    """

    db_path: Path = Path("data") / "corp_site.db"
    app_title: str = "Корпоративный портал"
    org_name: str = 'ООО "ЗАВОД РУСНИТ"'
    background_dir: Path = Path("app") / "static" / "backgrounds"
    greeting_dir: Path = Path("app") / "static" / "greetings"
    rotation_seconds: int = 30
    empty_rotation_seconds: int = 20
    check_time: str = "06:00"
    timezone: str = "Europe/Moscow"
    weather_lat: float = 54.6269
    weather_lon: float = 39.6916
    weather_refresh_minutes: int = 60
    weather_openweathermap_key: str = ""
    weather_wttr_city: str = "Ryazan"
    ticker_speed: int = 40
    news_enabled: bool = True
    news_fetch_minutes: int = 15
    news_max_items: int = 6
    admin_username: str = ""
    admin_password: str = ""
    admin_password_hash: str = ""

    @model_validator(mode="after")
    def admin_credentials_ok(self):
        """Требует хотя бы один способ проверки пароля: открытый или bcrypt-хэш."""
        pw = self.admin_password
        h = self.admin_password_hash

        if not pw and not h:
            raise ValueError(
                "Нужны учётные данные администратора: CORP_ADMIN_PASSWORD "
                "или CORP_ADMIN_PASSWORD_HASH (bcrypt)."
            )
        if pw:
            if len(pw) < 8:
                raise ValueError(
                    "Пароль администратора должен быть не менее 8 символов."
                )
            if pw == "admin":
                raise ValueError(
                    "Пароль 'admin' запрещён. Задайте надёжный пароль."
                )
        if h and not h.startswith("$2"):
            raise ValueError(
                "CORP_ADMIN_PASSWORD_HASH должен быть bcrypt-хэшем "
                "(префикс $2a$/$2b$/$2y$)."
            )
        return self

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, v: str) -> str:
        """Проверяет, что часовой пояс существует (валидный IANA-идентификатор)."""
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError:
            raise ValueError(
                f"Неизвестный часовой пояс: '{v}'. "
                "Примеры: Europe/Moscow, Asia/Yekaterinburg, UTC."
            )
        return v

    model_config = {
        "env_prefix": "CORP_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "frozen": True,
    }


try:
    settings = Settings()
except Exception as e:
    print(f"\n[ОШИБКА КОНФИГУРАЦИИ]\n{e}\n", file=sys.stderr)
    sys.exit(1)
