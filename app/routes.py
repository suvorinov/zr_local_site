"""Маршруты веб-приложения.

Определяет эндпоинты для главной страницы и управления контентом.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import (
    add_announcement,
    add_employee,
    count_announcements,
    count_employees,
    deactivate_announcement,
    delete_announcement,
    delete_employee,
    get_announcements,
    get_birthday_employees,
    get_employees,
    log_greeting,
    search_employees,
)
from app.image_gen import generate_greeting
from app.models import EmployeeCreate
from app.weather import get_all_forecast, get_forecast

logger = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


def _dfmt(value) -> str:
    """Преобразует дату/дату-время в ДД.ММ.ГГГГ."""
    if not value:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d.%m.%Y")
    parts = str(value).split("-")
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return str(value)


templates.env.filters["dfmt"] = _dfmt

STATIC_URL = "/static"


def _get_today_greetings() -> list[dict]:
    """Собирает все элементы для показа на главной странице.

    Включает поздравления именинников и активные объявления.
    Если изображение для именинника ещё не сгенерировано —
    создаёт его на лету.

    Returns:
        Список элементов для ротации.
    """
    items: list[dict] = []

    birthday_employees = get_birthday_employees()
    for emp in birthday_employees:
        greeting_name = f"greeting_{emp['name'].replace(' ', '_')}.jpg"
        greeting_path = settings.greeting_dir / greeting_name
        if not greeting_path.exists():
            try:
                abs_path = generate_greeting(
                    employee_name=emp["name"],
                    gender=emp["gender"],
                )
                log_greeting(emp["id"], abs_path)
                greeting_path = Path(abs_path)
                logger.info("Поздравление создано на лету для %s", emp["name"])
            except Exception as e:
                logger.error("Ошибка генерации для %s: %s", emp["name"], e)
                continue
        items.append({
            "type": "birthday",
            "text": f"С Днём Рождения, {emp['name']}!",
            "image_path": f"{STATIC_URL}/greetings/{greeting_path.name}",
            "employee_name": emp["name"],
        })

    announcements = get_announcements(active_only=True)
    for ann in announcements:
        items.append({
            "type": "announcement",
            "text": ann["text"],
            "image_path": None,
            "employee_name": None,
        })

    return items


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница с поздравлениями и объявлениями.

    Если на сегодня нет ни именинников, ни объявлений —
    показывает страницу-информер с датой, названием
    организации и прогнозом погоды.
    """
    items = _get_today_greetings()
    template = "index.html"
    ctx: dict = {
        "items": items,
        "title": settings.app_title,
        "rotation_seconds": settings.rotation_seconds,
    }

    if not items:
        template = "informer.html"
        ctx["org_name"] = settings.org_name
        now = datetime.now()
        days_ru = ["понедельник","вторник","среда","четверг",
                    "пятница","суббота","воскресенье"]
        months_ru = ["января","февраля","марта","апреля","мая",
                      "июня","июля","августа","сентября",
                      "октября","ноября","декабря"]
        ctx["today"] = (
            f"{days_ru[now.weekday()]}, "
            f"{now.day} {months_ru[now.month-1]} {now.year}"
        ).capitalize()
        ctx["forecast"] = get_forecast()
        ctx["forecast_all"] = json.dumps(get_all_forecast(), ensure_ascii=False)

    return templates.TemplateResponse(request, template, ctx)


@router.get("/admin", response_class=HTMLResponse)
async def admin_redirect():
    """Редирект на раздел сотрудников."""
    return RedirectResponse(url="/admin/employees")


@router.get("/admin/employees", response_class=HTMLResponse)
async def admin_employees(
    request: Request,
    name: str = Query(default=""),
    birthday: str = Query(default=""),
    page: int = Query(default=1, ge=1),
):
    """Панель управления сотрудниками с поиском и пагинацией."""
    per_page = 10
    offset = (page - 1) * per_page
    employees = search_employees(name=name, birthday=birthday, limit=per_page, offset=offset)
    total = count_employees(name=name, birthday=birthday)
    total_pages = max(1, (total + per_page - 1) // per_page)
    today = date.today()
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "section": "employees",
            "employees": employees,
            "today": today,
            "search_name": name,
            "search_birthday": birthday,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "title": f"{settings.app_title} — Сотрудники",
        },
    )


@router.get("/admin/announcements", response_class=HTMLResponse)
async def admin_announcements(
    request: Request,
    page: int = Query(default=1, ge=1),
    search_date_from: str = Query(default=""),
    search_date_to: str = Query(default=""),
):
    """Панель управления объявлениями с пагинацией и фильтром по датам."""
    per_page = 10
    offset = (page - 1) * per_page
    announcements = get_announcements(
        active_only=False,
        limit=per_page,
        offset=offset,
        search_date_from=search_date_from,
        search_date_to=search_date_to,
    )
    total = count_announcements(
        active_only=False,
        search_date_from=search_date_from,
        search_date_to=search_date_to,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    today = date.today()
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "section": "announcements",
            "announcements": announcements,
            "today": today,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "search_date_from": search_date_from,
            "search_date_to": search_date_to,
            "title": f"{settings.app_title} — Объявления",
        },
    )


@router.post("/admin/employees/add")
async def add_employee_route(name: str = Form(...), birthday: str = Form(...), gender: str = Form(...)):
    """Добавляет нового сотрудника."""
    employee_data = EmployeeCreate(
        name=name,
        birthday=date.fromisoformat(birthday),
        gender=gender,
    )
    add_employee(employee_data.name, employee_data.birthday, employee_data.gender)
    logger.info("Сотрудник добавлен через веб: %s", name)
    return RedirectResponse(url="/admin/employees", status_code=303)


@router.post("/admin/employees/{employee_id}/delete")
async def delete_employee_route(employee_id: int):
    """Удаляет сотрудника."""
    ok = delete_employee(employee_id)
    logger.info("Удаление сотрудника id=%d: %s", employee_id, "успех" if ok else "не найден")
    return RedirectResponse(url="/admin/employees", status_code=303)


@router.post("/admin/announcements/add")
async def add_announcement_route(
    text: str = Form(...),
    date_from: str = Form(default=""),
    date_to: str = Form(default=""),
):
    """Добавляет новое объявление с опциональной привязкой к датам."""
    add_announcement(
        text=text,
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
    )
    logger.info("Объявление добавлено через веб: %s", text[:50])
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.post("/admin/announcements/{announcement_id}/deactivate")
async def deactivate_announcement_route(announcement_id: int):
    """Деактивирует объявление."""
    ok = deactivate_announcement(announcement_id)
    logger.info("Деактивация объявления id=%d: %s", announcement_id, "успех" if ok else "не найдено")
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.post("/admin/announcements/{announcement_id}/delete")
async def delete_announcement_route(announcement_id: int):
    """Удаляет объявление."""
    ok = delete_announcement(announcement_id)
    logger.info("Удаление объявления id=%d: %s", announcement_id, "успех" if ok else "не найдено")
    return RedirectResponse(url="/admin/announcements", status_code=303)
