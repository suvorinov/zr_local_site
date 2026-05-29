"""Работа с базой данных SQLite.

Обеспечивает инициализацию и CRUD операции.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from app.config import settings


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Создаёт подключение к SQLite.

    Args:
        db_path: Путь к файлу БД. По умолчанию из настроек.

    Returns:
        Объект подключения к SQLite.
    """
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """Контекстный менеджер для работы с БД.

    Yields:
        Объект подключения к SQLite.
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Инициализирует таблицы в базе данных."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                birthday TEXT NOT NULL,
                gender TEXT NOT NULL CHECK(gender IN ('male', 'female'))
            );

            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                is_active INTEGER NOT NULL DEFAULT 1,
                date_from TEXT,
                date_to TEXT
            );

            CREATE TABLE IF NOT EXISTS greetings_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                image_path TEXT,
                created_at TEXT NOT NULL DEFAULT (date('now')),
                FOREIGN KEY (employee_id) REFERENCES employees(id)
            );
        """)


def get_employees() -> list[dict]:
    """Возвращает список всех сотрудников.

    Returns:
        Список словарей с данными сотрудников.
    """
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM employees ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def search_employees(
    name: str = "", birthday: str = "",
    limit: int = 0, offset: int = 0,
) -> list[dict]:
    """Ищет сотрудников по ФИО и/или дате рождения с пагинацией.

    Args:
        name: Часть ФИО для поиска (LIKE).
        birthday: Дата рождения для поиска (точное совпадение).
        limit: Максимум записей (0 = все).
        offset: Смещение.

    Returns:
        Список подходящих сотрудников.
    """
    query = "SELECT * FROM employees WHERE 1=1"
    params: list[str] = []
    if name:
        query += " AND name LIKE ?"
        params.append(f"%{name}%")
    if birthday:
        query += " AND birthday = ?"
        params.append(birthday)
    query += " ORDER BY name"
    if limit:
        query += " LIMIT ? OFFSET ?"
        params.extend([str(limit), str(offset)])
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def count_employees(name: str = "", birthday: str = "") -> int:
    """Возвращает количество сотрудников по фильтру.

    Args:
        name: Часть ФИО для поиска (LIKE).
        birthday: Дата рождения для поиска (точное совпадение).

    Returns:
        Количество записей.
    """
    query = "SELECT COUNT(*) FROM employees WHERE 1=1"
    params: list[str] = []
    if name:
        query += " AND name LIKE ?"
        params.append(f"%{name}%")
    if birthday:
        query += " AND birthday = ?"
        params.append(birthday)
    with get_db() as conn:
        return conn.execute(query, params).fetchone()[0]


def get_employee(employee_id: int) -> dict | None:
    """Возвращает сотрудника по ID.

    Args:
        employee_id: Идентификатор сотрудника.

    Returns:
        Данные сотрудника или None.
    """
    with get_db() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        return dict(row) if row else None


def add_employee(name: str, birthday: date, gender: str) -> int:
    """Добавляет нового сотрудника.

    Args:
        name: ФИО сотрудника.
        birthday: Дата рождения.
        gender: Пол (male/female).

    Returns:
        ID созданной записи.
    """
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO employees (name, birthday, gender) VALUES (?, ?, ?)",
            (name, birthday.isoformat(), gender),
        )
        return cur.lastrowid


def delete_employee(employee_id: int) -> bool:
    """Удаляет сотрудника по ID и связанные записи в логе.

    Args:
        employee_id: Идентификатор сотрудника.

    Returns:
        True если запись удалена, иначе False.
    """
    with get_db() as conn:
        conn.execute("DELETE FROM greetings_log WHERE employee_id = ?", (employee_id,))
        cur = conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        return cur.rowcount > 0


def get_birthday_employees() -> list[dict]:
    """Находит сотрудников с днём рождения сегодня.

    Returns:
        Список сотрудников у которых сегодня день рождения.
    """
    today = date.today()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM employees WHERE strftime('%m-%d', birthday) = ?",
            (today.strftime("%m-%d"),),
        ).fetchall()
        return [dict(r) for r in rows]


def get_announcements(
    active_only: bool = True,
    limit: int = 0, offset: int = 0,
    search_date_from: str = "", search_date_to: str = "",
) -> list[dict]:
    """Возвращает список объявлений с пагинацией и фильтром по датам.

    При active_only=True учитывается привязка к датам:
    - date_from IS NULL или date_from <= сегодня
    - date_to IS NULL или date_to >= сегодня

    Args:
        active_only: Только активные объявления.
        limit: Максимум записей (0 = все).
        offset: Смещение.
        search_date_from: Фильтр date_from >= значение.
        search_date_to: Фильтр date_to <= значение.

    Returns:
        Список объявлений.
    """
    today = date.today().isoformat()
    params: list[str] = []
    where_clauses: list[str] = []

    if active_only:
        where_clauses.append("is_active = 1")
        where_clauses.append("(date_from IS NULL OR date_from <= ?)")
        params.append(today)
        where_clauses.append("(date_to IS NULL OR date_to >= ?)")
        params.append(today)

    if search_date_from:
        where_clauses.append("date_from IS NOT NULL AND date_from >= ?")
        params.append(search_date_from)

    if search_date_to:
        where_clauses.append("date_to IS NOT NULL AND date_to <= ?")
        params.append(search_date_to)

    query = "SELECT * FROM announcements"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY created_at DESC"
    if limit:
        query += " LIMIT ? OFFSET ?"
        params.extend([str(limit), str(offset)])

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def count_announcements(
    active_only: bool = True,
    search_date_from: str = "", search_date_to: str = "",
) -> int:
    """Возвращает количество объявлений с фильтром по датам.

    Args:
        active_only: Только активные.
        search_date_from: Фильтр date_from >= значение.
        search_date_to: Фильтр date_to <= значение.

    Returns:
        Количество записей.
    """
    today = date.today().isoformat()
    params: list[str] = []
    where_clauses: list[str] = []

    if active_only:
        where_clauses.append("is_active = 1")
        where_clauses.append("(date_from IS NULL OR date_from <= ?)")
        params.append(today)
        where_clauses.append("(date_to IS NULL OR date_to >= ?)")
        params.append(today)

    if search_date_from:
        where_clauses.append("date_from IS NOT NULL AND date_from >= ?")
        params.append(search_date_from)

    if search_date_to:
        where_clauses.append("date_to IS NOT NULL AND date_to <= ?")
        params.append(search_date_to)

    query = "SELECT COUNT(*) FROM announcements"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    with get_db() as conn:
        return conn.execute(query, params).fetchone()[0]


def add_announcement(text: str, date_from: date | None = None, date_to: date | None = None) -> int:
    """Добавляет новое объявление.

    Args:
        text: Текст объявления.
        date_from: Дата начала показа.
        date_to: Дата окончания показа.

    Returns:
        ID созданной записи.
    """
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO announcements (text, created_at, date_from, date_to) VALUES (?, ?, ?, ?)",
            (
                text,
                datetime.now().isoformat(),
                date_from.isoformat() if date_from else None,
                date_to.isoformat() if date_to else None,
            ),
        )
        return cur.lastrowid


def deactivate_announcement(announcement_id: int) -> bool:
    """Деактивирует объявление по ID.

    Args:
        announcement_id: Идентификатор объявления.

    Returns:
        True если запись обновлена, иначе False.
    """
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE announcements SET is_active = 0 WHERE id = ?",
            (announcement_id,),
        )
        return cur.rowcount > 0


def delete_announcement(announcement_id: int) -> bool:
    """Удаляет объявление по ID.

    Args:
        announcement_id: Идентификатор объявления.

    Returns:
        True если запись удалена, иначе False.
    """
    with get_db() as conn:
        cur = conn.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
        return cur.rowcount > 0


def log_greeting(employee_id: int, image_path: str) -> int:
    """Логирует создание поздравления.

    Args:
        employee_id: ID сотрудника.
        image_path: Путь к изображению.

    Returns:
        ID записи в логе.
    """
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO greetings_log (employee_id, image_path, created_at) VALUES (?, ?, date('now'))",
            (employee_id, image_path),
        )
        return cur.lastrowid
