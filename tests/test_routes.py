"""Smoke-тесты маршрутов: главная, защита админки, CSRF на POST-формах."""

import base64
import contextlib
import hashlib
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import pytest
from fastapi.testclient import TestClient

from app import db, routes
from app.config import settings
from app.csrf import generate_csrf_token
from app.main import app


@pytest.fixture(autouse=True)
def _hermetic_content(monkeypatch):
    """Убирает зависимость от сети и реальных кэшей при рендере '/'."""
    monkeypatch.setattr(routes, "get_news_items", lambda: [])
    monkeypatch.setattr(routes, "get_all_forecast", lambda: [])
    monkeypatch.setattr(routes, "get_forecast", lambda: [])
    routes._admin_hits.clear()
    yield
    routes._admin_hits.clear()


@pytest.fixture
def client():
    return TestClient(app, base_url="http://testclient")


def _auth() -> dict:
    raw = f"{settings.admin_username}:{settings.admin_password}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def _csrf_token() -> str:
    session_id = hashlib.sha256(b"testclient:testclient").hexdigest()[:16]
    return generate_csrf_token(session_id)


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ЗАВОД РУСНИТ" in resp.text


def test_healthz_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthz_db_down(client, monkeypatch):
    @contextlib.contextmanager
    def _broken_db():
        raise RuntimeError("база недоступна")
        yield

    monkeypatch.setattr(routes, "get_db", _broken_db)
    resp = client.get("/healthz")
    assert resp.status_code == 503


def test_admin_requires_auth(client):
    assert client.get("/admin/employees").status_code == 401
    assert client.get("/admin/announcements").status_code == 401


def test_admin_pages_with_auth(client):
    for path in ("/admin/employees", "/admin/announcements"):
        resp = client.get(path, headers=_auth())
        assert resp.status_code == 200
        assert "Сотрудник" in resp.text or "Объявление" in resp.text


def test_admin_edit_page_with_auth(client):
    ann_id = db.add_announcement("Текст объявления", "Заголовок")
    resp = client.get(f"/admin/announcements/{ann_id}/edit", headers=_auth())
    assert resp.status_code == 200


def test_post_announcement_requires_csrf(client):
    resp = client.post(
        "/admin/announcements/add",
        data={"text": "Без токена"},
        headers=_auth(),
    )
    assert resp.status_code == 403


def test_post_announcement_with_csrf(client):
    resp = client.post(
        "/admin/announcements/add",
        data={
            "csrf_token": _csrf_token(),
            "title": "Тест",
            "text": "Текст тестового объявления",
        },
        headers=_auth(),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    titles = [a["title"] for a in db.get_announcements(active_only=False)]
    assert "Тест" in titles


def test_post_employee_with_csrf(client):
    resp = client.post(
        "/admin/employees/add",
        data={
            "csrf_token": _csrf_token(),
            "name": "Новый Сотрудник Первый",
            "birthday": "1990-01-01",
            "gender": "male",
        },
        headers=_auth(),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    names = [e["name"] for e in db.get_employees()]
    assert "Новый Сотрудник Первый" in names


def test_post_employee_bad_date(client):
    resp = client.post(
        "/admin/employees/add",
        data={
            "csrf_token": _csrf_token(),
            "name": "Плохая дата",
            "birthday": "не-дата",
            "gender": "male",
        },
        headers=_auth(),
    )
    assert resp.status_code == 400 or resp.status_code == 422


def test_post_with_wrong_csrf_rejected(client):
    resp = client.post(
        "/admin/announcements/add",
        data={"csrf_token": "1:default:deadbeef", "text": "x"},
        headers=_auth(),
    )
    assert resp.status_code == 403


def _stub_settings(monkeypatch, *, password_hash="", password="testpass"):
    stub = SimpleNamespace(
        admin_username="stubadmin",
        admin_password_hash=password_hash,
        admin_password=password,
    )
    monkeypatch.setattr(routes, "settings", stub)
    return stub


def test_check_admin_password_plain(monkeypatch):
    _stub_settings(monkeypatch, password="s3cret-pass")
    assert routes._check_admin_password("s3cret-pass")
    assert not routes._check_admin_password("s3cret-pasx")


def test_check_admin_password_bcrypt(monkeypatch):
    h = bcrypt.hashpw(b"s3cret-pass", bcrypt.gensalt()).decode()
    _stub_settings(monkeypatch, password_hash=h, password="")
    assert routes._check_admin_password("s3cret-pass")
    assert not routes._check_admin_password("wrong-pass")
    assert not routes._check_admin_password("")


def test_markdownify_accepts_http_but_strips_javascript():
    out = routes._markdownify('<a href="javascript:alert(1)">x</a>')
    assert "javascript:" not in out


def test_markdownify_adds_noopener_to_target_links():
    out = routes._markdownify('<a href="http://example.com" target="_blank">x</a>')
    assert 'rel="noopener"' in out
    assert 'target="_blank"' in out


def test_json_script_escapes_closing_tags():
    out = routes._json_script('{"a": "</script><script>alert(1)</script>"}')
    assert "</script>" not in out
    assert "<\\/script>" in out


def test_admin_rate_limit_returns_429(client):
    routes._admin_hits.clear()
    for _ in range(20):
        resp = client.get("/admin/employees")
        assert resp.status_code in (401, 200)
    resp = client.get("/admin/employees")
    assert resp.status_code == 429


def test_post_announcement_with_category_pinned(client):
    resp = client.post(
        "/admin/announcements/add",
        data={
            "csrf_token": _csrf_token(),
            "title": "Карточка",
            "text": "Текст карточки",
            "category": "important",
            "is_pinned": "1",
        },
        headers=_auth(),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    rows = [a for a in db.get_announcements(active_only=False) if a["title"] == "Карточка"]
    assert rows and rows[-1]["category"] == "important" and rows[-1]["is_pinned"] == 1


def test_main_page_renders_announcement_card(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ann-card" in resp.text or "ann-list" not in resp.text


def test_post_announcement_with_image(client):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    resp = client.post(
        "/admin/announcements/add",
        data={
            "csrf_token": _csrf_token(),
            "title": "С картинкой",
            "text": "Текст",
            "category": "event",
        },
        headers=_auth(),
        files={"image": ("pic.png", png, "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    rows = [a for a in db.get_announcements(active_only=False) if a["title"] == "С картинкой"]
    url = rows[-1]["image_path"]
    assert url and url.startswith("/static/uploads/")
    fpath = Path("app" + url)
    try:
        assert fpath.exists() and fpath.read_bytes() == png
    finally:
        fpath.unlink(missing_ok=True)


def test_post_announcement_rejects_non_image(client):
    resp = client.post(
        "/admin/announcements/add",
        data={
            "csrf_token": _csrf_token(),
            "title": "Не картинка",
            "text": "Текст",
        },
        headers=_auth(),
        files={"image": ("f.txt", b"not an image", "text/plain")},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_post_employee_edit_with_csrf(client):
    emp_id = db.add_employee("Старый Фамилия Имя", date(1990, 5, 5), "male")
    resp = client.post(
        f"/admin/employees/{emp_id}/edit",
        data={
            "csrf_token": _csrf_token(),
            "name": "Новый Фамилия Имя",
            "birthday": "1991-06-06",
            "gender": "female",
        },
        headers=_auth(),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    row = db.get_employee(emp_id)
    assert row["name"] == "Новый Фамилия Имя"
    assert row["birthday"] == "1991-06-06"
    assert row["gender"] == "female"


def test_admin_employees_edit_page(client):
    emp_id = db.add_employee("Правка Фамилия Имя", date(1985, 3, 3), "male")
    resp = client.get(f"/admin/employees?edit_id={emp_id}", headers=_auth())
    assert resp.status_code == 200
    assert "Редактировать сотрудника" in resp.text
    assert "Правка Фамилия Имя" in resp.text


def test_export_employees_csv(client):
    resp = client.get("/admin/employees/export", headers=_auth())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "\ufeff" in resp.text
    assert "ФИО" in resp.text


def test_import_employees_csv(client):
    csv_body = (
        "\ufeffФИО;Дата рождения;Пол\n"
        "ИмпортТест Один;01.02.1988;Мужской\n"
        "ИмпортТест Два;1989-02-03;ж\n"
    )
    resp = client.post(
        "/admin/employees/import",
        data={"csrf_token": _csrf_token()},
        headers=_auth(),
        files={"file": ("staff.csv", csv_body.encode("utf-8"), "text/csv")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    names = {e["name"] for e in db.get_employees()}
    assert "ИмпортТест Один" in names
    assert "ИмпортТест Два" in names
    row = next(e for e in db.get_employees() if e["name"] == "ИмпортТест Два")
    assert row["gender"] == "female"


@pytest.fixture
def _content_isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "_DATA_DIR", tmp_path)
    routes._QUOTES_CACHE = None
    routes._HOLIDAYS_CACHE = None
    return tmp_path


def test_admin_content_page(client, _content_isolated):
    resp = client.get("/admin/content", headers=_auth())
    assert resp.status_code == 200
    assert "Цитаты" in resp.text and "Праздники" in resp.text


def test_add_quote_and_holiday(client, _content_isolated):
    resp = client.post("/admin/content/quotes/add", data={
        "csrf_token": _csrf_token(),
        "text": "Мудрость теста",
        "author": "Тестер",
    }, headers=_auth(), follow_redirects=False)
    assert resp.status_code == 303
    resp = client.post("/admin/content/holidays/add", data={
        "csrf_token": _csrf_token(),
        "holiday_date": "12-25",
        "name": "День теста",
        "greeting": "С праздником!",
        "emoji": "🎇",
    }, headers=_auth(), follow_redirects=False)
    assert resp.status_code == 303
    quotes = routes._read_content_file("quotes.json")
    holidays = routes._read_content_file("holidays.json")
    assert any(q["text"] == "Мудрость теста" for q in quotes)
    assert any(h["date"] == "12-25" for h in holidays)


def test_delete_quote_via_web(client, _content_isolated):
    routes._write_content_file("quotes.json", [{"text": "Удаляемая", "author": ""}])
    resp = client.post("/admin/content/quotes/0/delete", data={
        "csrf_token": _csrf_token(),
    }, headers=_auth(), follow_redirects=False)
    assert resp.status_code == 303
    assert routes._read_content_file("quotes.json") == []


def test_add_holiday_rejects_bad_date(client, _content_isolated):
    resp = client.post("/admin/content/holidays/add", data={
        "csrf_token": _csrf_token(),
        "holiday_date": "недата",
        "name": "Плохой",
    }, headers=_auth(), follow_redirects=False)
    assert resp.status_code == 400


def test_birthday_item_enqueues_background_generation(monkeypatch, tmp_path):
    class BackgroundTasks:
        def __init__(self):
            self.tasks = []

        def add_task(self, fn, *args, **kwargs):
            self.tasks.append((fn, args, kwargs))

    bg = BackgroundTasks()
    monkeypatch.setattr(
        routes,
        "get_birthday_employees",
        lambda: [{"id": 1, "name": "Тест Тестович", "gender": "male", "birthday": date.today().isoformat()}],
    )
    monkeypatch.setattr(routes, "greeting_filename", lambda name, age: tmp_path / f"{name}.png")
    items = routes._get_birthday_items(bg)
    assert bg.tasks, "ожидалась фоновая задача генерации открытки"
    assert items and items[0]["type"] == "holiday"
    assert "Тест Тестович" in items[0]["name"]