"""Smoke-тесты маршрутов: главная, защита админки, CSRF на POST-формах."""

import base64
import hashlib

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