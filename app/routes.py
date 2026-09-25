"""Маршруты веб-приложения.

Определяет эндпоинты для главной страницы и управления контентом.
"""

import json
import logging
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import bleach
import markdown as md_lib

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app import timeutils
from app.config import settings
from app.csrf import generate_csrf_token, get_session_id, require_csrf
from app.db import (
    add_announcement,
    add_employee,
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
from app.feed import get_news_items
from app.image_gen import compute_age, generate_greeting, greeting_filename, is_jubilee_age
from app.models import EmployeeCreate
from app.weather import get_all_forecast, get_forecast

logger = logging.getLogger(__name__)
router = APIRouter()

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

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


def _cleanup_old_greetings(employee_name: str, current: Path) -> None:
    """Удаляет устаревшие открытки сотрудника (например, прошлого возраста).

    Args:
        employee_name: ФИО сотрудника.
        current: Путь к актуальной открытке, которую нельзя удалять.
    """
    safe_name = re.sub(r'[^\w\s-]', '', employee_name).strip().replace(' ', '_')
    for old in settings.greeting_dir.glob(f"greeting_{safe_name}*.jpg"):
        if old.resolve() != Path(current).resolve():
            try:
                old.unlink(missing_ok=True)
                logger.info("Удалена устаревшая открытка: %s", old.name)
            except OSError as e:
                logger.warning("Не удалось удалить %s: %s", old.name, e)


def _get_birthday_items() -> list[dict]:
    """Собирает поздравления именинников для показа карточками.

    Если изображение для именинника ещё не сгенерировано —
    создаёт его на лету с учётом пола и возраста (юбилей).

    Returns:
        Список элементов типа birthday для ротации.
    """
    items: list[dict] = []
    today = timeutils.today()

    birthday_employees = get_birthday_employees()
    for emp in birthday_employees:
        age = compute_age(emp.get("birthday"), today)
        greeting_path = greeting_filename(emp["name"], age)
        if not greeting_path.exists():
            try:
                abs_path = generate_greeting(
                    employee_name=emp["name"],
                    gender=emp["gender"],
                    age=age,
                )
                log_greeting(emp["id"], abs_path)
                greeting_path = Path(abs_path)
                logger.info("Поздравление создано для %s", emp["name"])
                _cleanup_old_greetings(emp["name"], greeting_path)
            except Exception as e:
                logger.error("Ошибка генерации для %s: %s", emp["name"], e)
                continue

        if is_jubilee_age(age):
            text = f"С Юбилеем, {emp['name']}!"
        else:
            text = f"С Днём Рождения, {emp['name']}!"

        items.append({
            "type": "birthday",
            "text": text,
            "image_path": f"{STATIC_URL}/greetings/{greeting_path.name}",
            "employee_name": emp["name"],
        })

    return items


_HOLIDAYS_CACHE: list[dict] | None = None


def _get_holiday_items(today: date | None = None) -> list[dict]:
    """Собирает слайд-карточки праздников на текущий день.

    Праздники берутся из holidays.json и показываются CSS-карточкой
    в общей ротации с именинниками.

    Args:
        today: Дата проверки (по умолчанию сегодняшняя).

    Returns:
        Список элементов типа holiday, если на дату есть праздники.
    """
    global _HOLIDAYS_CACHE
    if _HOLIDAYS_CACHE is None:
        holidays_file = _DATA_DIR / "holidays.json"
        try:
            raw = json.loads(holidays_file.read_text(encoding="utf-8"))
            _HOLIDAYS_CACHE = raw if isinstance(raw, list) else []
        except (OSError, json.JSONDecodeError):
            logger.error("Не удалось загрузить %s", holidays_file)
            _HOLIDAYS_CACHE = []

    today = today or timeutils.today()
    md = f"{today.month:02d}-{today.day:02d}"
    return [
        {
            "type": "holiday",
            "name": h.get("name", ""),
            "greeting": h.get("greeting", "Праздник!"),
            "emoji": h.get("emoji", "\U0001f389"),
        }
        for h in _HOLIDAYS_CACHE
        if h.get("date") == md
    ]


def _get_ticker_items() -> list[str]:
    """Собирает тексты активных объявлений для бегущей строки.

    Returns:
        Список строк (заголовок + текст) активных объявлений.
    """
    announcements = get_announcements(active_only=True)
    return [
        (ann.get("title", "") + (" — " if ann.get("title") else "") + ann["text"])
        for ann in announcements
    ]


_QUOTES_CACHE: list[dict] | None = None


def _get_quotes() -> list[dict]:
    """Загружает список цитат из quotes.json (с кэшем).

    Дубликаты текстов отбрасываются — каждая цитата показывается
    ровно один раз за цикл.

    Returns:
        Список уникальных словарей {text, author}. При ошибке — резервная цитата.
    """
    global _QUOTES_CACHE
    if _QUOTES_CACHE is None:
        quotes_file = _DATA_DIR / "quotes.json"
        try:
            raw = json.loads(quotes_file.read_text(encoding="utf-8"))
            if not isinstance(raw, list) or not raw:
                raise ValueError("quotes.json пуст или не является списком")
            seen: set[str] = set()
            unique: list[dict] = []
            for item in raw:
                text = str(item.get("text", "")).strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                unique.append({"text": text, "author": str(item.get("author", "")).strip()})
            if not unique:
                raise ValueError("quotes.json не содержит цитат")
            _QUOTES_CACHE = unique
        except (OSError, json.JSONDecodeError, ValueError):
            logger.error("Не удалось загрузить %s, использую резервную цитату", quotes_file)
            _QUOTES_CACHE = [{
                "text": "Работа избавляет нас от трёх великих зол: скуки, порока и нужды.",
                "author": "Вольтер",
            }]
    return _QUOTES_CACHE


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    """Склонение существительных: 1 день / 2 дня / 5 дней."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return forms[0]
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return forms[1]
    return forms[2]


def _short_name(full: str) -> str:
    """Сокращает ФИО до «Фамилия И.О.»: Суворинов Олег Викторович -> Суворинов О.В."""
    parts = full.split()
    if not parts:
        return full
    surname = parts[0]
    initials = "".join(p[0] + "." for p in parts[1:] if p)
    return f"{surname} {initials}".strip() if initials else surname


def _get_upcoming_birthdays(horizon: int = 3) -> list[dict]:
    """Группирует ближайшие дни рождения по дням.

    Учитываются только дни строго после сегодняшнего (сегодняшние
    показываются карточками-слайдами). Каждый сотрудник попадает
    в первую подходящую дату его дня рождения.

    Args:
        horizon: Сколько ближайших дней учитывать (по умолчанию 3).

    Returns:
        Список словарей {days, label, names} только для дней,
        где есть именинники, отсортированный по близости даты.
    """
    today = timeutils.today()
    buckets: dict[int, list[str]] = {}
    for emp in get_employees():
        try:
            bd = date.fromisoformat(emp["birthday"])
        except (ValueError, TypeError):
            continue
        for delta in range(1, horizon + 1):
            target = today + timedelta(days=delta)
            if (bd.month, bd.day) == (target.month, target.day):
                buckets.setdefault(delta, []).append(_short_name(emp["name"]))
                break

    labels = {1: "Завтра", 2: "Послезавтра"}
    result: list[dict] = []
    for delta in sorted(buckets):
        label = labels.get(delta) or f"Через {delta} {_plural(delta, ('день', 'дня', 'дней'))}"
        result.append({"days": delta, "label": label, "names": buckets[delta]})
    return result


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Главная страница-информер.

    Показывает informer.html с датой, временем, погодой,
    карточками именинников и бегущей строкой объявлений внизу.
    """
    items = _get_birthday_items() + _get_holiday_items()
    ticker_items = _get_ticker_items()

    now = timeutils.now()
    days_ru = ["понедельник","вторник","среда","четверг",
                "пятница","суббота","воскресенье"]
    days_ru_short = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    months_ru = ["января","февраля","марта","апреля","мая",
                  "июня","июля","августа","сентября",
                  "октября","ноября","декабря"]

    next_birthdays = _get_upcoming_birthdays(horizon=3)
    quotes = _get_quotes()
    quote = random.choice(quotes)
    news = get_news_items()

    forecast = get_forecast()
    forecast_all = get_all_forecast()
    pressure_mm = (
        forecast[0]["pressure_mm"]
        if forecast and forecast[0].get("pressure_mm") is not None
        else None
    )

    ctx: dict = {
        "title": settings.app_title,
        "org_name": settings.org_name,
        "today": (
            f"{days_ru[now.weekday()]}, "
            f"{now.day} {months_ru[now.month-1]} {now.year}"
        ).capitalize(),
        "today_short": (
            f"{days_ru_short[now.weekday()]}, "
            f"{now.day:02d}.{now.month:02d}.{now.year}"
        ),
        "forecast": forecast,
        "forecast_all": json.dumps(forecast_all, ensure_ascii=False),
        "pressure_mm": pressure_mm,
        "items": items,
        "ticker_items": ticker_items,
        "ticker_speed": settings.ticker_speed,
        "rotation_seconds": settings.rotation_seconds,
        "empty_rotation_seconds": settings.empty_rotation_seconds,
        "upcoming_birthdays": next_birthdays,
        "quote_text": quote["text"],
        "quote_author": quote["author"],
        "quotes_json": json.dumps(quotes, ensure_ascii=False),
        "news": news,
        "news_json": json.dumps(news, ensure_ascii=False),
    }

    return templates.TemplateResponse(
        request, "informer.html", ctx,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_redirect(_: None = Depends(verify_admin)):
    """Редирект на раздел сотрудников."""
    return RedirectResponse(url="/admin/employees")


@router.get("/admin/employees", response_class=HTMLResponse)
def admin_employees(
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
    today = timeutils.today()
    session_id = get_session_id(request)
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
def admin_announcements(
    request: Request,
    page: int = Query(default=1, ge=1),
    search_date_from: str = Query(default=""),
    search_date_to: str = Query(default=""),
    edit_id: int | None = Query(default=None),
    _: None = Depends(verify_admin),
):
    """Панель управления объявлениями с пагинацией и фильтром по датам."""
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
    today = timeutils.today()
    session_id = get_session_id(request)
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
def add_employee_route(
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
def delete_employee_route(
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
def add_announcement_route(
    request: Request,
    _: None = Depends(verify_admin),
    csrf_token: str = Form(default=""),
    title: str = Form(default=""),
    text: str = Form(...),
    date_from: str = Form(default=""),
    date_to: str = Form(default=""),
    priority: int = Form(default=0),
):
    """Добавляет новое объявление (бегущая строка — только текст и сроки)."""
    require_csrf(request, csrf_token)
    add_announcement(
        title=title,
        text=text,
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        priority=priority,
    )
    logger.info("Объявление добавлено через веб: %s", title or text[:50])
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.get("/admin/announcements/{announcement_id}/edit", response_class=HTMLResponse)
def edit_announcement_page(
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
    today = timeutils.today()
    session_id = get_session_id(request)
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
def edit_announcement_route(
    request: Request,
    announcement_id: int,
    _: None = Depends(verify_admin),
    csrf_token: str = Form(default=""),
    title: str = Form(default=""),
    text: str = Form(...),
    date_from: str = Form(default=""),
    date_to: str = Form(default=""),
    priority: int = Form(default=0),
):
    """Обновляет объявление (бегущая строка — только текст и сроки)."""
    require_csrf(request, csrf_token)
    update_announcement(
        announcement_id=announcement_id,
        title=title,
        text=text,
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        priority=priority,
    )
    logger.info("Объявление id=%d отредактировано через веб", announcement_id)
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.post("/admin/announcements/{announcement_id}/deactivate")
def deactivate_announcement_route(
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
def delete_announcement_route(
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
