"""Тесты слоя БД: CRUD, пагинация, деактивация, лог поздравлений."""

from datetime import date, timedelta

from app import db
from app.timeutils import today


def test_employee_crud():
    emp_id = db.add_employee("Иванов Иван Иванович", date(1990, 5, 15), "male")

    emp = db.get_employee(emp_id)
    assert emp is not None
    assert emp["name"] == "Иванов Иван Иванович"
    assert emp["gender"] == "male"

    assert db.count_employees() == 1
    found = db.search_employees(name="Иванов")
    assert [e["id"] for e in found] == [emp_id]

    assert db.delete_employee(emp_id) is True
    assert db.get_employee(emp_id) is None
    assert db.delete_employee(emp_id) is False


def test_search_employees_pagination():
    ids = [
        db.add_employee(f"Сотрудник {i}", date(1990, 1, i + 1), "female")
        for i in range(5)
    ]
    page = db.search_employees(limit=2, offset=2)
    assert len(page) == 2
    assert set(r["id"] for r in page).issubset(ids)

    assert db.count_employees(name="Сотрудник") == 5
    assert db.count_employees(name="Нет такого") == 0


def test_birthday_employees():
    t = today()
    db.add_employee("Именинник", t, "male")
    db.add_employee("Не именинник", t - timedelta(days=10), "female")

    names = {e["name"] for e in db.get_birthday_employees()}
    assert names == {"Именинник"}


def test_announcement_crud_and_dates():
    past = date(2020, 1, 1)
    future = date(2999, 1, 1)

    ann_id = db.add_announcement(
        "Один раз", "Заголовок",
        date_from=past, date_to=future, priority=5, is_pinned=True,
    )
    ann = db.get_announcement(ann_id)
    assert ann["title"] == "Заголовок"
    assert ann["is_pinned"] == 1
    assert db.count_announcements() == 1
    assert db.count_announcements(active_only=False) == 1

    busy = db.add_announcement("Вне периода", date_from=future, date_to=future)
    active_titles = {a["title"] for a in db.get_announcements(active_only=True)}
    assert active_titles == {"Заголовок"}

    all_titles = {a["title"] for a in db.get_announcements(active_only=False)}
    assert all_titles == {"Заголовок", ""}

    expired = db.add_announcement("Просрочка", date_to=past)
    assert db.auto_deactivate_expired() == 1
    assert db.get_announcement(expired)["is_active"] == 0

    assert db.delete_announcement(busy) is True
    assert db.delete_announcement(busy) is False


def test_update_announcement_sentinel():
    ann_id = db.add_announcement(
        "Текст", "Старый",
        date_from=date(2026, 1, 1), date_to=date(2026, 12, 31),
    )

    db.update_announcement(ann_id, title="Новый")
    ann = db.get_announcement(ann_id)
    assert ann["title"] == "Новый"
    assert ann["date_from"] == "2026-01-01"

    db.update_announcement(ann_id, date_from=None, date_to=None)
    ann = db.get_announcement(ann_id)
    assert ann["date_from"] is None
    assert ann["date_to"] is None

    db.update_announcement(ann_id, image_path="pic.jpg")
    db.update_announcement(ann_id, image_path="")
    assert db.get_announcement(ann_id)["image_path"] is None

    assert db.update_announcement(ann_id) is False
    assert db.update_announcement(99999, title="x") is False


def test_greeting_log_and_cascade():
    emp_id = db.add_employee("Колесов Максим Сергеевич", date(1989, 9, 25), "male")
    log_id = db.log_greeting(emp_id, "app/static/greetings/greet.jpg")
    assert log_id > 0

    with db.get_db() as conn:
        rows = conn.execute("SELECT COUNT(*) FROM greetings_log WHERE employee_id=?", (emp_id,)).fetchone()[0]
    assert rows == 1

    db.delete_employee(emp_id)
    with db.get_db() as conn:
        rows = conn.execute("SELECT COUNT(*) FROM greetings_log WHERE employee_id=?", (emp_id,)).fetchone()[0]
    assert rows == 0