"""Планировщик ежедневной проверки дней рождений.

Запускает проверку в 06:00 и генерирует поздравления.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db import get_birthday_employees, log_greeting
from app.image_gen import generate_greeting

logger = logging.getLogger(__name__)


def check_birthdays():
    """Проверяет список сотрудников и генерирует поздравления.

    Находит всех сотрудников с днём рождения сегодня,
    генерирует для каждого поздравительное изображение.
    """
    logger.info("Проверка дней рождений на %s", datetime.now().strftime("%Y-%m-%d"))
    employees = get_birthday_employees()

    if not employees:
        logger.info("Сегодня именинников нет")
        return

    logger.info("Найдено именинников: %d", len(employees))

    for emp in employees:
        try:
            image_path = generate_greeting(
                employee_name=emp["name"],
                gender=emp["gender"],
            )
            log_greeting(emp["id"], image_path)
            logger.info("Поздравление создано для %s", emp["name"])
        except Exception as e:
            logger.error("Ошибка генерации для %s: %s", emp["name"], e)


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
        id="birthday_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Планировщик запущен. Проверка в %s ежедневно", settings.check_time)
    return scheduler
