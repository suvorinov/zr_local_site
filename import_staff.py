"""Импорт штата сотрудников из data/staff.txt в базу данных.

Формат файла (разделитель — табуляция, первая строка — заголовок):
    Фамилия\tИмя\tОтчество\tПол\tДата рождения

Пол задаётся словами «Мужской»/«Женский» (регистр не важен),
дата рождения — ДД.ММ.ГГГГ.

По умолчанию (--reset) таблица сотрудников и журнал поздравлений
очищаются перед импортом: база полностью пересобирается из файла.
С --no-reset выполняется частичная досинхронизация по ФИО:
существующие записи обновляются, новые добавляются.

Пример:
    python import_staff.py --reset
"""

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from app.db import get_connection

logger = logging.getLogger(__name__)

STAFF_FILE = Path("data") / "staff.txt"

GENDER_MAP = {
    "мужской": "male", "м": "male", "муж": "male", "m": "male", "1": "male",
    "женский": "female", "ж": "female", "жен": "female", "f": "female", "0": "female",
}


def parse_staff(file_path: Path) -> tuple[list[dict], list[str]]:
    """Читает staff.txt и возвращает записи сотрудников.

    Args:
        file_path: Путь к файлу с персоналом.

    Returns:
        Кортеж (записи, ошибки). Каждая запись — словарь
        {name, birthday, gender}.
    """
    raw = file_path.read_text(encoding="utf-8-sig").splitlines()
    records: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()

    for line_no, line in enumerate(raw, start=1):
        if line_no == 1 or not line.strip():
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 5:
            errors.append(f"строка {line_no}: ожидалось 5 колонок, получено {len(parts)}")
            continue

        surname, first, patronymic, gender_raw, birthday_raw = parts[:5]
        name = " ".join(p for p in (surname, first, patronymic) if p)
        if not name:
            errors.append(f"строка {line_no}: пустое ФИО")
            continue

        gender = GENDER_MAP.get(gender_raw.strip().lower())
        if not gender:
            errors.append(f"строка {line_no}: неизвестный пол «{gender_raw}»")
            continue

        birthday = None
        for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
            try:
                birthday = datetime.strptime(birthday_raw, fmt).date().isoformat()
                break
            except ValueError:
                continue
        if not birthday:
            errors.append(f"строка {line_no}: не удалось разобрать дату «{birthday_raw}»")
            continue

        if name in seen:
            errors.append(f"строка {line_no}: дубликат ФИО «{name}» пропущен")
            continue
        seen.add(name)

        records.append({"name": name, "birthday": birthday, "gender": gender})

    return records, errors


def reset_employees(conn) -> None:
    """Полностью очищает журнал поздравлений и таблицу сотрудников."""
    conn.execute("DELETE FROM greetings_log")
    conn.execute("DELETE FROM employees")


def reconcile(conn, records: list[dict]) -> tuple[int, int, int]:
    """Синхронизирует сотрудников с файлом.

    Args:
        conn: Соединение с БД.
        records: Записи из файла.

    Returns:
        Кортеж (вставлено, обновлено, удалено).
    """
    existing = {
        row["name"]: row for row in
        conn.execute("SELECT id, name, birthday, gender FROM employees")
    }

    inserted = updated = 0
    for rec in records:
        row = existing.get(rec["name"])
        if row is None:
            conn.execute(
                "INSERT INTO employees (name, birthday, gender) VALUES (?, ?, ?)",
                (rec["name"], rec["birthday"], rec["gender"]),
            )
            inserted += 1
        else:
            if row["birthday"] != rec["birthday"] or row["gender"] != rec["gender"]:
                conn.execute(
                    "UPDATE employees SET birthday = ?, gender = ? WHERE id = ?",
                    (rec["birthday"], rec["gender"], row["id"]),
                )
                updated += 1
            existing[rec["name"]]["synced"] = True

    to_delete = [row["id"] for row in existing.values() if not row.get("synced")]
    for emp_id in to_delete:
        conn.execute("DELETE FROM greetings_log WHERE employee_id = ?", (emp_id,))
        conn.execute("DELETE FROM employees WHERE id = ?", (emp_id,))

    return inserted, updated, len(to_delete)


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт персонала из staff.txt")
    parser.add_argument("--source", default=str(STAFF_FILE), help="Путь к staff.txt")
    parser.add_argument("--no-reset", action="store_true",
                        help="Не очищать базу: досинхронизировать по ФИО")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        sys.exit(f"Файл не найден: {source}")

    records, errors = parse_staff(source)
    for err in errors:
        print(f"[пропущено] {err}")

    with get_connection() as conn:
        if args.no_reset:
            inserted, updated, removed = reconcile(conn, records)
        else:
            reset_employees(conn)
            inserted = 0
            updated = 0
            for rec in records:
                conn.execute(
                    "INSERT INTO employees (name, birthday, gender) VALUES (?, ?, ?)",
                    (rec["name"], rec["birthday"], rec["gender"]),
                )
                inserted += 1
            removed = 0

    print()
    print(f"Всего в файле: {len(records)}")
    print(f"Вставлено: {inserted}, обновлено: {updated}, удалено: {removed}, "
          f"пропущено: {len(errors)}")


if __name__ == "__main__":
    main()