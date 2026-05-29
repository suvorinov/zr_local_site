"""Конфигурация приложения.

Содержит настройки путей, базы данных и параметров генерации.
"""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения.

    Attributes:
        db_path: Путь к файлу SQLite базы данных.
        app_title: Название приложения.
        background_dir: Путь к каталогу с фоновыми изображениями.
        greeting_dir: Путь к каталогу для сгенерированных поздравлений.
        rotation_seconds: Интервал ротации поздравлений в секундах.
        check_time: Время проверки дней рождений (ЧЧ:ММ).
    """

    db_path: Path = Path("data") / "corp_site.db"
    app_title: str = "Корпоративный портал"
    org_name: str = 'ООО "ЗАВОД РУСНИТ"'
    background_dir: Path = Path("app") / "static" / "backgrounds"
    greeting_dir: Path = Path("app") / "static" / "greetings"
    rotation_seconds: int = 60
    check_time: str = "06:00"
    weather_lat: float =  54.6269
    weather_lon: float = 39.6916

    model_config = {
        "env_prefix": "CORP_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "frozen": True,
    }


settings = Settings()
