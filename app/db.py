"""Работа с базой данных SQLite.

Обеспечивает инициализацию и CRUD операции.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from app.config import settings
from app.timeutils import now, today

logger = logging.getLogger(__name__)


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Создаёт подключение к SQLite.

    Args:
        db_path: Путь к файлу БД. По умолчанию из настроек.

    Returns:
        Объект подключения к SQLite.
    """
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
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


def _run_migration(conn: sqlite3.Connection):
    """Добавляет новые колонки в существующие таблицы."""
    migrations = [
        "ALTER TABLE announcements ADD COLUMN title TEXT DEFAULT ''",
        "ALTER TABLE announcements ADD COLUMN priority INTEGER DEFAULT 0",
        "ALTER TABLE announcements ADD COLUMN category TEXT DEFAULT 'info'",
        "ALTER TABLE announcements ADD COLUMN is_pinned INTEGER DEFAULT 0",
        "ALTER TABLE announcements ADD COLUMN image_path TEXT DEFAULT NULL",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            logger.info("Миграция: %s", sql)
        except sqlite3.OperationalError:
            pass


def init_db():
    """Инициализирует таблицы в базе данных."""
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                birthday TEXT NOT NULL,
                gender TEXT NOT NULL CHECK(gender IN ('male', 'female'))
            );

            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT DEFAULT '',
                text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                is_active INTEGER NOT NULL DEFAULT 1,
                date_from TEXT,
                date_to TEXT,
                priority INTEGER DEFAULT 0,
                category TEXT DEFAULT 'info',
                is_pinned INTEGER DEFAULT 0,
                image_path TEXT DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS greetings_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                image_path TEXT,
                created_at TEXT NOT NULL DEFAULT (date('now')),
                FOREIGN KEY (employee_id) REFERENCES employees(id)
            );
        """)
        _run_migration(conn)


def get_employees() -> list[dict]:
    """Возвращает список всех сотрудников.

    Returns:
        Список словарей с данными сотрудников.
    """
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM employees ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def _build_employee_where(name: str = "", birthday: str = ""):
    where = " WHERE 1=1"
    params: list[str] = []
    if name:
        where += " AND name LIKE ?"
        params.append(f"%{name}%")
    if birthday:
        where += " AND birthday = ?"
        params.append(birthday)
    return where, params


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
    where, params = _build_employee_where(name, birthday)
    query = "SELECT * FROM employees" + where + " ORDER BY name"
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
    where, params = _build_employee_where(name, birthday)
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM employees" + where, params).fetchone()[0]


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
        emp_id = cur.lastrowid
        logger.info("Добавлен сотрудник id=%d: %s", emp_id, name)
        return emp_id


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
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Удалён сотрудник id=%d", employee_id)
        else:
            logger.warning("Сотрудник id=%d не найден для удаления", employee_id)
        return deleted


def update_employee(employee_id: int, name: str, birthday: date, gender: str) -> bool:
    """Обновляет данные сотрудника.

    Args:
        employee_id: Идентификатор сотрудника.
        name: Новое ФИО.
        birthday: Новая дата рождения.
        gender: Новый пол (male/female).

    Returns:
        True если запись обновлена, иначе False.
    """
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE employees SET name = ?, birthday = ?, gender = ? WHERE id = ?",
            (name, birthday.isoformat(), gender, employee_id),
        )
        ok = cur.rowcount > 0
        if ok:
            logger.info("Обновлён сотрудник id=%d: %s", employee_id, name)
        else:
            logger.warning("Сотрудник id=%d не найден для обновления", employee_id)
        return ok


def get_birthday_employees() -> list[dict]:
    """Находит сотрудников с днём рождения сегодня.

    Returns:
        Список сотрудников у которых сегодня день рождения.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM employees WHERE strftime('%m-%d', birthday) = ?",
            (today().strftime("%m-%d"),),
        ).fetchall()
        return [dict(r) for r in rows]


def _build_announcement_where(
    active_only: bool = True,
    search_date_from: str = "",
    search_date_to: str = "",
):
    today_iso = today().isoformat()
    params: list[str] = []
    where_clauses: list[str] = []

    if active_only:
        where_clauses.append("is_active = 1")
        where_clauses.append("(date_from IS NULL OR date_from <= ?)")
        params.append(today_iso)
        where_clauses.append("(date_to IS NULL OR date_to >= ?)")
        params.append(today_iso)

    if search_date_from:
        where_clauses.append("date_from IS NOT NULL AND date_from >= ?")
        params.append(search_date_from)

    if search_date_to:
        where_clauses.append("date_to IS NOT NULL AND date_to <= ?")
        params.append(search_date_to)

    where = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    return where, params


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
    where, params = _build_announcement_where(active_only, search_date_from, search_date_to)
    query = "SELECT * FROM announcements" + where + " ORDER BY is_pinned DESC, priority DESC, created_at DESC"
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
    where, params = _build_announcement_where(active_only, search_date_from, search_date_to)
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM announcements" + where, params).fetchone()[0]


def get_announcement(announcement_id: int) -> dict | None:
    """Возвращает объявление по ID.

    Args:
        announcement_id: Идентификатор объявления.

    Returns:
        Данные объявления или None.
    """
    with get_db() as conn:
        row = conn.execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
        return dict(row) if row else None


def add_announcement(
    text: str,
    title: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    priority: int = 0,
    category: str = "info",
    is_pinned: bool = False,
    image_path: str | None = None,
) -> int:
    """Добавляет новое объявление.

    Args:
        text: Текст объявления.
        title: Заголовок объявления.
        date_from: Дата начала показа.
        date_to: Дата окончания показа.
        priority: Приоритет.
        category: Категория оформления.
        is_pinned: Закреплено.
        image_path: Путь к изображению.

    Returns:
        ID созданной записи.
    """
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO announcements (title, text, created_at, date_from, date_to, priority, category, is_pinned, image_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                text,
                now().isoformat(),
                date_from.isoformat() if date_from else None,
                date_to.isoformat() if date_to else None,
                priority,
                category,
                1 if is_pinned else 0,
                image_path,
            ),
        )
        ann_id = cur.lastrowid
        logger.info("Добавлено объявление id=%d: %s", ann_id, title or text[:50])
        return ann_id


# Маркер «поле не передано» — нужен, чтобы None/пустая строка значили
# «сбросить значение (NULL)», а не «не менять».
_UNSET = object()


def update_announcement(
    announcement_id: int,
    title: str | None = _UNSET,
    text: str | None = _UNSET,
    date_from: date | None | str = _UNSET,
    date_to: date | None | str = _UNSET,
    priority: int | None = _UNSET,
    category: str | None = _UNSET,
    is_pinned: bool | None = _UNSET,
    image_path: str | None = _UNSET,
) -> bool:
    """Обновляет объявление по ID.

    Args:
        announcement_id: Идентификатор объявления.
        title: Новый заголовок.
        text: Новый текст.
        date_from: Новая дата начала (None или пустая строка = сбросить).
        date_to: Новая дата окончания (None или пустая строка = сбросить).
        priority: Новый приоритет.
        category: Новая категория.
        is_pinned: Новый флаг закрепления.
        image_path: Новый путь к изображению (None или пустая строка = сбросить).

    Returns:
        True если запись обновлена, иначе False.
    """
    def _as_iso(value) -> str | None:
        if not value:
            return None
        if isinstance(value, str):
            return value
        return value.isoformat()

    fields: list[str] = []
    params: list = []

    if title is not _UNSET:
        fields.append("title = ?")
        params.append(title)
    if text is not _UNSET:
        fields.append("text = ?")
        params.append(text)
    if date_from is not _UNSET:
        fields.append("date_from = ?")
        params.append(_as_iso(date_from))
    if date_to is not _UNSET:
        fields.append("date_to = ?")
        params.append(_as_iso(date_to))
    if priority is not _UNSET:
        fields.append("priority = ?")
        params.append(priority)
    if category is not _UNSET:
        fields.append("category = ?")
        params.append(category)
    if is_pinned is not _UNSET:
        fields.append("is_pinned = ?")
        params.append(1 if is_pinned else 0)
    if image_path is not _UNSET:
        fields.append("image_path = ?")
        params.append(image_path or None)

    if not fields:
        return False

    params.append(announcement_id)
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE announcements SET " + ", ".join(fields) + " WHERE id = ?",
            params,
        )
        updated = cur.rowcount > 0
        if updated:
            logger.info("Обновлено объявление id=%d", announcement_id)
        else:
            logger.warning("Объявление id=%d не найдено для обновления", announcement_id)
        return updated


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
        deactivated = cur.rowcount > 0
        if deactivated:
            logger.info("Деактивировано объявление id=%d", announcement_id)
        else:
            logger.warning("Объявление id=%d не найдено для деактивации", announcement_id)
        return deactivated


def auto_deactivate_expired() -> int:
    """Деактивирует объявления с истекшей date_to.

    Returns:
        Количество деактивированных записей.
    """
    today_iso = today().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE announcements SET is_active = 0 WHERE is_active = 1 AND date_to IS NOT NULL AND date_to < ?",
            (today_iso,),
        )
        count = cur.rowcount
        if count:
            logger.info("Автоматически деактивировано %d просроченных объявлений", count)
        return count


def delete_announcement(announcement_id: int) -> bool:
    """Удаляет объявление по ID.

    Args:
        announcement_id: Идентификатор объявления.

    Returns:
        True если запись удалена, иначе False.
    """
    with get_db() as conn:
        cur = conn.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Удалено объявление id=%d", announcement_id)
        else:
            logger.warning("Объявление id=%d не найдено для удаления", announcement_id)
        return deleted


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
            "INSERT INTO greetings_log (employee_id, image_path, created_at) VALUES (?, ?, ?)",
            (employee_id, image_path, today().isoformat()),
        )
        return cur.lastrowid
