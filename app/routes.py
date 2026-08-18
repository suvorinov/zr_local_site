"""Маршруты веб-приложения.

Определяет эндпоинты для главной страницы и управления контентом.
"""

import hashlib
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

import bleach
import markdown as md_lib

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.csrf import generate_csrf_token, require_csrf
from app.db import (
    add_announcement,
    add_employee,
    auto_deactivate_expired,
    count_announcements,
    count_employees,
    deactivate_announcement,
    delete_announcement,
    delete_employee,
    get_announcement,
    get_announcements,
    get_birthday_employees,
    get_employees,
    log_greeting,
    search_employees,
    update_announcement,
)
from app.image_gen import generate_greeting
from app.models import EmployeeCreate
from app.weather import get_all_forecast, get_forecast

logger = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

security = HTTPBasic(auto_error=False)

# Разрешённые HTML-теги для Markdown-рендеринга
_BLEACH_ALLOWED_TAGS = {
    "p", "br", "strong", "em", "b", "i", "u", "s",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "code", "hr",
    "a", "img",
}

_BLEACH_ALLOWED_ATTRS = {
    "a": ["href", "title", "target"],
    "img": ["src", "alt", "title"],
}


def _get_session_id(request: Request) -> str:
    """Вычисляет session ID по IP + User-Agent для привязки CSRF."""
    client_ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    return hashlib.sha256(f"{client_ip}:{ua}".encode()).hexdigest()[:16]


def verify_admin(credentials: HTTPBasicCredentials | None = Depends(security)):
    if not credentials or credentials.username != settings.admin_username or credentials.password != settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверные учётные данные",
            headers={"WWW-Authenticate": "Basic"},
        )


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


def _markdownify(text: str) -> str:
    """Конвертирует Markdown в санитизированный HTML.

    Использует bleach для очистки от potentially dangerous тегов
    (script, iframe, и т.д.) — защита от XSS.
    """
    if not text:
        return ""
    html = md_lib.markdown(text, extensions=["nl2br"])
    return bleach.clean(
        html,
        tags=_BLEACH_ALLOWED_TAGS,
        attributes=_BLEACH_ALLOWED_ATTRS,
        strip=True,
    )


templates.env.filters["markdown"] = _markdownify
STATIC_URL = "/static"


def _get_birthday_items() -> list[dict]:
    """Собирает поздравления именинников для показа карточками.

    Если изображение для именинника ещё не сгенерировано —
    создаёт его на лету.

    Returns:
        Список элементов типа birthday для ротации.
    """
    items: list[dict] = []

    birthday_employees = get_birthday_employees()
    for emp in birthday_employees:
        safe_name = re.sub(r'[^\w\s-]', '', emp['name']).strip().replace(' ', '_')
        greeting_name = f"greeting_{safe_name}.jpg"
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

    return items


def _get_ticker_items() -> list[str]:
    """Собирает тексты активных объявлений для бегущей строки.

    Returns:
        Список строк (заголовок + текст) активных объявлений.
    """
    auto_deactivate_expired()
    announcements = get_announcements(active_only=True)
    return [
        (ann.get("title", "") + (" — " if ann.get("title") else "") + ann["text"])
        for ann in announcements
    ]


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница-информер.

    Показывает informer.html с датой, временем, погодой,
    карточками именинников и бегущей строкой объявлений внизу.
    """
    items = _get_birthday_items()
    ticker_items = _get_ticker_items()

    now = datetime.now()
    days_ru = ["понедельник","вторник","среда","четверг",
                "пятница","суббота","воскресенье"]
    months_ru = ["января","февраля","марта","апреля","мая",
                  "июня","июля","августа","сентября",
                  "октября","ноября","декабря"]

    ctx: dict = {
        "title": settings.app_title,
        "org_name": settings.org_name,
        "today": (
            f"{days_ru[now.weekday()]}, "
            f"{now.day} {months_ru[now.month-1]} {now.year}"
        ).capitalize(),
        "forecast": get_forecast(),
        "forecast_all": json.dumps(get_all_forecast(), ensure_ascii=False),
        "items": items,
        "ticker_items": ticker_items,
        "ticker_speed": settings.ticker_speed,
        "rotation_seconds": settings.rotation_seconds,
    }

    return templates.TemplateResponse(request, "informer.html", ctx)


@router.get("/admin", response_class=HTMLResponse)
async def admin_redirect(_: None = Depends(verify_admin)):
    """Редирект на раздел сотрудников."""
    return RedirectResponse(url="/admin/employees")


@router.get("/admin/employees", response_class=HTMLResponse)
async def admin_employees(
    request: Request,
    name: str = Query(default=""),
    birthday: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    _: None = Depends(verify_admin),
):
    """Панель управления сотрудниками с поиском и пагинацией."""
    per_page = 10
    offset = (page - 1) * per_page
    employees = search_employees(name=name, birthday=birthday, limit=per_page, offset=offset)
    total = count_employees(name=name, birthday=birthday)
    total_pages = max(1, (total + per_page - 1) // per_page)
    today = date.today()
    session_id = _get_session_id(request)
    csrf_token = generate_csrf_token(session_id)
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
            "csrf_token": csrf_token,
        },
    )


@router.get("/admin/announcements", response_class=HTMLResponse)
async def admin_announcements(
    request: Request,
    page: int = Query(default=1, ge=1),
    search_date_from: str = Query(default=""),
    search_date_to: str = Query(default=""),
    edit_id: int | None = Query(default=None),
    _: None = Depends(verify_admin),
):
    """Панель управления объявлениями с пагинацией и фильтром по датам."""
    auto_deactivate_expired()
    edit_ann = get_announcement(edit_id) if edit_id else None
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
    session_id = _get_session_id(request)
    csrf_token = generate_csrf_token(session_id)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "section": "announcements",
            "announcements": announcements,
            "edit_announcement": edit_ann,
            "today": today,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "search_date_from": search_date_from,
            "search_date_to": search_date_to,
            "title": f"{settings.app_title} — Объявления",
            "csrf_token": csrf_token,
        },
    )


@router.post("/admin/employees/add")
async def add_employee_route(
    request: Request,
    name: str = Form(...),
    birthday: str = Form(...),
    gender: str = Form(...),
    csrf_token: str = Form(default=""),
    _: None = Depends(verify_admin),
):
    """Добавляет нового сотрудника."""
    require_csrf(request, csrf_token)
    employee_data = EmployeeCreate(
        name=name,
        birthday=date.fromisoformat(birthday),
        gender=gender,
    )
    add_employee(employee_data.name, employee_data.birthday, employee_data.gender)
    logger.info("Сотрудник добавлен через веб: %s", name)
    return RedirectResponse(url="/admin/employees", status_code=303)


@router.post("/admin/employees/{employee_id}/delete")
async def delete_employee_route(
    request: Request,
    employee_id: int,
    csrf_token: str = Form(default=""),
    _: None = Depends(verify_admin),
):
    """Удаляет сотрудника."""
    require_csrf(request, csrf_token)
    ok = delete_employee(employee_id)
    logger.info("Удаление сотрудника id=%d: %s", employee_id, "успех" if ok else "не найден")
    return RedirectResponse(url="/admin/employees", status_code=303)


@router.post("/admin/announcements/add")
async def add_announcement_route(
    request: Request,
    _: None = Depends(verify_admin),
    csrf_token: str = Form(default=""),
    title: str = Form(default=""),
    text: str = Form(...),
    date_from: str = Form(default=""),
    date_to: str = Form(default=""),
    priority: int = Form(default=0),
    category: str = Form(default="info"),
    is_pinned: bool = Form(default=False),
    image_path: str = Form(default=""),
):
    """Добавляет новое объявление."""
    require_csrf(request, csrf_token)
    add_announcement(
        title=title,
        text=text,
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        priority=priority,
        category=category,
        is_pinned=is_pinned,
        image_path=image_path or None,
    )
    logger.info("Объявление добавлено через веб: %s", title or text[:50])
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.get("/admin/announcements/{announcement_id}/edit", response_class=HTMLResponse)
async def edit_announcement_page(
    request: Request,
    announcement_id: int,
    _: None = Depends(verify_admin),
):
    """Страница редактирования объявления."""
    ann = get_announcement(announcement_id)
    if not ann:
        raise HTTPException(status_code=404, detail="Объявление не найдено")

    announcements = get_announcements(active_only=False)
    total = len(announcements)
    total_pages = 1
    today = date.today()
    session_id = _get_session_id(request)
    csrf_token = generate_csrf_token(session_id)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "section": "announcements",
            "announcements": announcements,
            "edit_announcement": ann,
            "today": today,
            "page": 1,
            "total_pages": total_pages,
            "total": total,
            "search_date_from": "",
            "search_date_to": "",
            "title": f"{settings.app_title} — Редактирование объявления",
            "csrf_token": csrf_token,
        },
    )


@router.post("/admin/announcements/{announcement_id}/edit")
async def edit_announcement_route(
    request: Request,
    announcement_id: int,
    _: None = Depends(verify_admin),
    csrf_token: str = Form(default=""),
    title: str = Form(default=""),
    text: str = Form(...),
    date_from: str = Form(default=""),
    date_to: str = Form(default=""),
    priority: int = Form(default=0),
    category: str = Form(default="info"),
    is_pinned: bool = Form(default=False),
    image_path: str = Form(default=""),
):
    """Обновляет объявление."""
    require_csrf(request, csrf_token)
    update_announcement(
        announcement_id=announcement_id,
        title=title,
        text=text,
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        priority=priority,
        category=category,
        is_pinned=is_pinned,
        image_path=image_path or None,
    )
    logger.info("Объявление id=%d отредактировано через веб", announcement_id)
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.post("/admin/announcements/{announcement_id}/deactivate")
async def deactivate_announcement_route(
    request: Request,
    announcement_id: int,
    csrf_token: str = Form(default=""),
    _: None = Depends(verify_admin),
):
    """Деактивирует объявление."""
    require_csrf(request, csrf_token)
    ok = deactivate_announcement(announcement_id)
    logger.info("Деактивация объявления id=%d: %s", announcement_id, "успех" if ok else "не найдено")
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.post("/admin/announcements/{announcement_id}/delete")
async def delete_announcement_route(
    request: Request,
    announcement_id: int,
    csrf_token: str = Form(default=""),
    _: None = Depends(verify_admin),
):
    """Удаляет объявление."""
    require_csrf(request, csrf_token)
    ok = delete_announcement(announcement_id)
    logger.info("Удаление объявления id=%d: %s", announcement_id, "успех" if ok else "не найдено")
    return RedirectResponse(url="/admin/announcements", status_code=303)
