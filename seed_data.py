"""Скрипт для заполнения БД тестовыми данными.

Запуск: python seed_data.py
"""

from datetime import date

from app.db import (
    add_announcement,
    add_employee,
    get_connection,
    init_db,
)


def seed():
    """Наполняет базу тестовыми сотрудниками и объявлением.

    Предварительно очищает все таблицы.
    """
    init_db()
    conn = get_connection()
    for table in ("greetings_log", "announcements", "employees"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()

    employees = [
        ("Иванов Иван Иванович", date(1990, 5, 28), "male"),
        ("Петрова Анна Сергеевна", date(1985, 5, 28), "female"),
        ("Сидоров Петр Алексеевич", date(1992, 3, 15), "male"),
        ("Кузнецова Елена Владимировна", date(1988, 7, 22), "female"),
        ("Смирнов Дмитрий Олегович", date(1995, 5, 28), "male"),
    ]

    for name, bday, gender in employees:
        add_employee(name, bday, gender)
        print(f"Добавлен: {name} ({bday})")

    add_announcement(
        "Уважаемые коллеги! Напоминаем о корпоративе "
        "в эту пятницу в 18:00.",
        date_from=date(2026, 5, 25),
        date_to=date(2026, 5, 31),
    )
    print("Добавлено объявление")


if __name__ == "__main__":
    seed()
