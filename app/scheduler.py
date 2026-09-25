"""Планировщик ежедневной проверки дней рождений.

Запускает проверку в 06:00 и генерирует поздравления.
"""

import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db import auto_deactivate_expired, get_birthday_employees, log_greeting
from app.image_gen import compute_age, generate_greeting, greeting_filename
from app.timeutils import now

logger = logging.getLogger(__name__)


def check_birthdays():
    """Проверяет список сотрудников и генерирует поздравления.

    Находит всех сотрудников с днём рождения сегодня,
    генерирует для каждого поздравительное изображение.
    """
    logger.info("Проверка дней рождений на %s", now().strftime("%Y-%m-%d"))
    employees = get_birthday_employees()

    if not employees:
        logger.info("Сегодня именинников нет")
        return

    logger.info("Найдено именинников: %d", len(employees))

    for emp in employees:
        try:
            age = compute_age(emp.get("birthday"))
            image_path = greeting_filename(emp["name"], age)
            if Path(image_path).exists():
                logger.info("Поздравление уже готово для %s", emp["name"])
                continue
            image_path = generate_greeting(
                employee_name=emp["name"],
                gender=emp["gender"],
                age=age,
            )
            log_greeting(emp["id"], image_path)
            logger.info("Поздравление создано для %s", emp["name"])
        except Exception as e:
            logger.error("Ошибка генерации для %s: %s", emp["name"], e)


def expire_old_announcements():
    """Гасит объявления с истёкшим сроком показа (раз в час)."""
    deactivated = auto_deactivate_expired()
    if deactivated:
        logger.info("Автоматически деактивировано %d просроченных объявлений", deactivated)


def setup_scheduler() -> BackgroundScheduler:
    """Настраивает и запускает планировщик.

    Returns:
        Настроенный экземпляр BackgroundScheduler.
    """
    scheduler = BackgroundScheduler()
    hour, minute = settings.check_time.split(":")
    scheduler.add_job(
        check_birthdays,
        "cron",
        hour=int(hour),
        minute=int(minute),
        timezone=ZoneInfo(settings.timezone),
        id="birthday_check",
        replace_existing=True,
    )
    scheduler.add_job(
        expire_old_announcements,
        "interval",
        hours=1,
        id="expire_announcements",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Планировщик запущен. Проверка в %s ежедневно", settings.check_time)
    return scheduler
