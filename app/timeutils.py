"""Работа с датой и временем в часовом поясе приложения.

Единственная точка истины для `now()` и `today()`:
все модули должны использовать их вместо `datetime.now()` / `date.today()`,
чтобы поведение не зависело от системного часового пояса (особенно в Docker,
где контейнер по умолчанию работает в UTC).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import settings


def now() -> datetime:
    """Текущее время в часовом поясе CORP_TIMEZONE.

    Returns:
        Timezone-aware datetime.
    """
    return datetime.now(ZoneInfo(settings.timezone))


def today() -> date:
    """Текущая дата в часовом поясе CORP_TIMEZONE.

    Returns:
        Объект даты (без времени).
    """
    return now().date()