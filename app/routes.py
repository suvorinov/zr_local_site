"""Маршруты веб-приложения.

Определяет эндпоинты для главной страницы и управления контентом.
"""

import csv
import hmac
import html
import html.parser
import io
import json
import logging
import random
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import bcrypt
import bleach
import markdown as md_lib

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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
    get_db,
    get_employee,
    get_employees,
    log_greeting,
    search_employees,
    update_announcement,
    update_employee,
)
from app.feed import get_news_items
from app.image_gen import compute_age, generate_greeting, greeting_filename, is_jubilee_age
from app.models import EmployeeCreate
from app.weather import get_all_forecast, get_forecast

logger = logging.getLogger(__name__)
router = APIRouter()

ANN_CATEGORY_LABELS = {
    "info": "Объявление",
    "important": "Важное",
    "event": "Событие",
    "congrats": "Поздравление",
}

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

# Разрешённые схемы URL: не зависеть от дефолтов bleach.
_BLEACH_PROTOCOLS = {"http", "https", "mailto"}

# Rate-limit для админ-эндпоинтов: срабатывает и за nginx, и без него.
# Простое скользящее окно (20 запросов в минуту) по реальному IP клиента
# (за прокси — X-Forwarded-For, иначе все клиенты сливаются в 127.0.0.1).
_ADMIN_RATE_MAX = 20
_ADMIN_RATE_WINDOW = 60

_admin_hits: dict[str, list[float]] = {}
_admin_lock = threading.Lock()


def _rate_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def admin_rate_limit(request: Request) -> None:
    """Ограничивает число обращений к админке с одного IP."""
    ip = _rate_key(request)
    now = time.monotonic()
    with _admin_lock:
        hits = [t for t in _admin_hits.get(ip, []) if t > now - _ADMIN_RATE_WINDOW]
        if len(hits) >= _ADMIN_RATE_MAX:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много запросов к админке. Подождите минуту.",
            )
        hits.append(now)
        _admin_hits[ip] = hits


def _check_admin_password(given: str) -> bool:
    """Проверяет пароль администратора: по bcrypt-хэшу или открытым сравнением."""
    h = settings.admin_password_hash
    if h:
        try:
            return bcrypt.checkpw(given.encode("utf-8"), h.encode("utf-8"))
        except ValueError:
            return False
    return hmac.compare_digest(given, settings.admin_password)


def verify_admin(credentials: HTTPBasicCredentials | None = Depends(security)):
    if not credentials or credentials.username != settings.admin_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверные учётные данные",
            headers={"WWW-Authenticate": "Basic"},
        )
    if not _check_admin_password(credentials.password):
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

    Использует bleach для очистки от потенциально опасных тегов
    (script, iframe и т.д.) — защита от XSS. Схемы URL ограничены
    явно, ссылки с target получают rel="noopener".
    """
    if not text:
        return ""
    html_str = md_lib.markdown(text, extensions=["nl2br"])
    clean = bleach.clean(
        html_str,
        tags=_BLEACH_ALLOWED_TAGS,
        attributes=_BLEACH_ALLOWED_ATTRS,
        protocols=_BLEACH_PROTOCOLS,
        strip=True,
    )
    return _add_rel_noopener(clean)


class _NoopenerRewriter(html.parser.HTMLParser):
    """Пересобирает HTML, добавляя rel="noopener" ссылкам с target."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def _emit(self, tag: str, attrs) -> None:
        pieces = [tag]
        for k, v in attrs:
            if v is None:
                pieces.append(k)
            else:
                pieces.append(f'{k}="{html.escape(v, quote=True)}"')
        self.out.append("<" + (" ".join(pieces)) + ">")

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            pool = dict(attrs)
            if "target" in pool and "rel" not in pool:
                attrs = list(attrs) + [("rel", "noopener")]
        self._emit(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")


def _add_rel_noopener(html_str: str) -> str:
    """Добавляет rel="noopener" ко всем ссылкам с target (защита от window.opener)."""
    parser = _NoopenerRewriter()
    parser.feed(html_str)
    parser.close()
    return "".join(parser.out)


def _json_script(value: str) -> str:
    """Обезопасивает JSON-строку для вставки в <script type="application/json">.

    Закрывает возможность преждевременного завершения блока тегом </script>
    (и комментария <!--) даже при наличии подобных строк в данных.
    """
    return (
        value.replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


templates.env.filters["markdown"] = _markdownify
templates.env.filters["json_script"] = _json_script
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


_GREETING_LOCKS: dict[str, threading.Lock] = {}
_GREETING_LOCKS_GUARD = threading.Lock()


def _greeting_lock(path: Path) -> threading.Lock:
    """Возвращает lock для пути открытки (защита от двойной генерации)."""
    with _GREETING_LOCKS_GUARD:
        return _GREETING_LOCKS.setdefault(str(path), threading.Lock())


def _generate_greeting_in_background(emp: dict, age: int, greeting_path: Path) -> None:
    """Генерирует открытку в фоновой задаче (после ответа клиенту)."""
    with _greeting_lock(greeting_path):
        if greeting_path.exists():
            return
        try:
            abs_path = generate_greeting(
                employee_name=emp["name"],
                gender=emp["gender"],
                age=age,
            )
            out = Path(abs_path)
            log_greeting(emp["id"], abs_path)
            logger.info("Поздравление создано в фоне для %s", emp["name"])
            _cleanup_old_greetings(emp["name"], out)
        except Exception as e:
            logger.error("Ошибка фоновой генерации для %s: %s", emp["name"], e)


def _get_birthday_items(background_tasks: BackgroundTasks | None = None) -> list[dict]:
    """Собирает поздравления именинников для показа карточками.

    Если изображение ещё не сгенерировано и передан background_tasks —
    сразу возвращает текстовую заглушку, а генерацию ставит в фон, чтобы
    GET / оставался мгновенным. Без background_tasks генерит на лету
    (автономные сценарии).

    Returns:
        Список элементов типа birthday/holiday для ротации.
    """
    items: list[dict] = []
    today = timeutils.today()

    birthday_employees = get_birthday_employees()
    for emp in birthday_employees:
        age = compute_age(emp.get("birthday"), today)
        greeting_path = greeting_filename(emp["name"], age)
        if not greeting_path.exists():
            if background_tasks is not None:
                background_tasks.add_task(
                    _generate_greeting_in_background, emp, age, greeting_path
                )
                items.append({
                    "type": "holiday",
                    "emoji": "\U0001F382",
                    "greeting": "С Днём Рождения!",
                    "name": emp["name"],
                })
                continue
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


@router.get("/healthz")
def healthz():
    """Проверка живости приложения (для HEALTHCHECK контейнера)."""
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception as e:
        logger.warning("Healthz: БД недоступна: %s", e)
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def index(request: Request, background_tasks: BackgroundTasks):
    """Главная страница-информер.

    Показывает informer.html с датой, временем, погодой,
    карточками именинников и бегущей строкой объявлений внизу.
    Открытки, которых ещё нет, догенерил довком в фоне (BackgroundTasks).
    """
    items = _get_birthday_items(background_tasks) + _get_holiday_items()
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
    announcements = [
        dict(a, category_label=ANN_CATEGORY_LABELS.get(a.get("category"), (a.get("category") or "info").capitalize()))
        for a in get_announcements(active_only=True)
    ]

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
        "announcements": announcements,
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
def admin_redirect(
    request: Request,
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Редирект на раздел сотрудников."""
    return RedirectResponse(url="/admin/employees")


@router.get("/admin/employees", response_class=HTMLResponse)
def admin_employees(
    request: Request,
    name: str = Query(default=""),
    birthday: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    edit_id: int | None = Query(default=None),
    report: str = Query(default=""),
    limit_ok: None = Depends(admin_rate_limit),
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
    edit_employee = get_employee(edit_id) if edit_id else None
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
            "edit_employee": edit_employee,
            "report": report,
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
    limit_ok: None = Depends(admin_rate_limit),
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
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Добавляет нового сотрудника."""
    require_csrf(request, csrf_token)
    try:
        birthday_date = date.fromisoformat(birthday)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректная дата рождения")
    employee_data = EmployeeCreate(
        name=name,
        birthday=birthday_date,
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
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Удаляет сотрудника."""
    require_csrf(request, csrf_token)
    ok = delete_employee(employee_id)
    logger.info("Удаление сотрудника id=%d: %s", employee_id, "успех" if ok else "не найден")
    return RedirectResponse(url="/admin/employees", status_code=303)


@router.post("/admin/employees/{employee_id}/edit")
def edit_employee_route(
    request: Request,
    employee_id: int,
    name: str = Form(...),
    birthday: str = Form(...),
    gender: str = Form(...),
    csrf_token: str = Form(default=""),
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Обновляет данные сотрудника."""
    require_csrf(request, csrf_token)
    try:
        birthday_date = date.fromisoformat(birthday)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректная дата рождения")
    employee_data = EmployeeCreate(
        name=name,
        birthday=birthday_date,
        gender=gender,
    )
    ok = update_employee(
        employee_id,
        employee_data.name,
        employee_data.birthday,
        employee_data.gender,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    logger.info("Сотрудник id=%d обновлён через веб: %s", employee_id, name)
    return RedirectResponse(url="/admin/employees", status_code=303)


@router.get("/admin/employees/export", response_class=Response)
def export_employees_route(
    request: Request,
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Выгружает сотрудников в CSV (точка с запятой, с BOM для Excel)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["ФИО", "Дата рождения", "Пол"])
    for emp in sorted(get_employees(), key=lambda e: e["name"]):
        writer.writerow([
            emp["name"],
            emp["birthday"],
            "Мужской" if emp["gender"] == "male" else "Женский",
        ])
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="employees.csv"'},
    )


_IMPORT_GENDER_MAP = {
    "мужской": "male", "муж": "male", "м": "male", "male": "male", "m": "male",
    "женский": "female", "жен": "female", "ж": "female", "female": "female", "f": "female",
}
_MAX_CSV_BYTES = 2 * 1024 * 1024


def _parse_employee_csv(content: bytes) -> tuple[list[dict], list[str]]:
    """Разбирает CSV сотрудников: ФИО;Дата рождения;Пол.

    Returns:
        Кортеж (записи {name, birthday, gender}, список ошибок).
    """
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    records: list[dict] = []
    errors: list[str] = []
    for line_no, row in enumerate(reader, start=2):
        name = (row.get("ФИО") or row.get("name") or "").strip()
        if not name:
            continue
        gender_raw = (row.get("Пол") or row.get("gender") or "").strip().lower()
        gender = _IMPORT_GENDER_MAP.get(gender_raw)
        if not gender:
            errors.append(f"строка {line_no}: неизвестный пол «{gender_raw}»")
            continue
        raw_birthday = (row.get("Дата рождения") or row.get("birthday") or "").strip()
        birthday: date | None = None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
            try:
                birthday = datetime.strptime(raw_birthday, fmt).date()
                break
            except ValueError:
                continue
        if not birthday:
            errors.append(f"строка {line_no}: не удалось разобрать дату «{raw_birthday}»")
            continue
        records.append({"name": name, "birthday": birthday, "gender": gender})
    return records, errors


@router.post("/admin/employees/import")
def import_employees_route(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(default=""),
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Импортирует сотрудников из CSV (досинхронизация по ФИО)."""
    require_csrf(request, csrf_token)
    content = file.file.read(_MAX_CSV_BYTES + 1)
    if len(content) > _MAX_CSV_BYTES:
        raise HTTPException(status_code=400, detail="Файл больше 2 МБ")
    records, parse_errors = _parse_employee_csv(content)
    if not records and not parse_errors:
        raise HTTPException(status_code=400, detail="В файле не найдено строк данных")

    by_name = {emp["name"]: emp for emp in get_employees()}
    added = updated = 0
    for rec in records:
        existing = by_name.get(rec["name"])
        if existing is None:
            add_employee(rec["name"], rec["birthday"], rec["gender"])
            added += 1
        elif existing["birthday"] != rec["birthday"].isoformat() or existing["gender"] != rec["gender"]:
            update_employee(existing["id"], rec["name"], rec["birthday"], rec["gender"])
            updated += 1

    lines = [f"импортировано: {added} новых, обновлено: {updated}"]
    for err in parse_errors:
        lines.append(f"пропущено ({err})")
    logger.info("CSV-импорт сотрудников: %s", "; ".join(lines))
    return RedirectResponse(
        url=f"/admin/employees?report={quote('; '.join(lines))}",
        status_code=303,
    )


_UPLOAD_DIR = Path("app") / "static" / "uploads"
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _save_announcement_image(upload: UploadFile | None) -> str | None:
    """Сохраняет загруженное изображение карточки и возвращает URL к нему."""
    if upload is None or not upload.filename:
        return None
    if upload.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Допускаются только изображения JPEG/PNG/GIF/WebP")
    data = upload.file.read(_MAX_IMAGE_BYTES + 1)
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Изображение больше 5 МБ")
    ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }[upload.content_type]
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"ann_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    (_UPLOAD_DIR / name).write_bytes(data)
    logger.info("Загружено изображение объявления: %s", name)
    return f"/static/uploads/{name}"


def _delete_announcement_image(url: str | None) -> None:
    """Удаляет файл изображения объявления (если путь в наших uploads)."""
    if not url or not url.startswith("/static/uploads/"):
        return
    try:
        Path("app" + url).unlink(missing_ok=True)
    except OSError:
        logger.warning("Не удалось удалить изображение: %s", url)


@router.post("/admin/announcements/add")
def add_announcement_route(
    request: Request,
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
    csrf_token: str = Form(default=""),
    title: str = Form(default=""),
    text: str = Form(...),
    date_from: str = Form(default=""),
    date_to: str = Form(default=""),
    priority: int = Form(default=0),
    category: str = Form(default="info"),
    is_pinned: int = Form(default=0),
    image: UploadFile | None = File(default=None),
):
    """Добавляет новое объявление: карточка в информере + бегущая строка."""
    require_csrf(request, csrf_token)
    try:
        start = date.fromisoformat(date_from) if date_from else None
        end = date.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректная дата")
    image_path = _save_announcement_image(image)
    try:
        add_announcement(
            title=title,
            text=text,
            date_from=start,
            date_to=end,
            priority=priority,
            category=category or "info",
            is_pinned=bool(is_pinned),
            image_path=image_path,
        )
    except Exception:
        if image_path:
            _delete_announcement_image(image_path)
        raise
    logger.info("Объявление добавлено через веб: %s", title or text[:50])
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.get("/admin/announcements/{announcement_id}/edit", response_class=HTMLResponse)
def edit_announcement_page(
    request: Request,
    announcement_id: int,
    limit_ok: None = Depends(admin_rate_limit),
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
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
    csrf_token: str = Form(default=""),
    title: str = Form(default=""),
    text: str = Form(...),
    date_from: str = Form(default=""),
    date_to: str = Form(default=""),
    priority: int = Form(default=0),
    category: str = Form(default="info"),
    is_pinned: int = Form(default=0),
    remove_image: int = Form(default=0),
    image: UploadFile | None = File(default=None),
):
    """Обновляет объявление: карточка в информере + бегущая строка."""
    require_csrf(request, csrf_token)
    try:
        start = date.fromisoformat(date_from) if date_from else None
        end = date.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректная дата")
    existing = get_announcement(announcement_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Объявление не найдено")
    old_image = existing.get("image_path")
    new_image = _save_announcement_image(image)
    if new_image:
        image_path = new_image
        _delete_announcement_image(old_image)
    elif remove_image:
        image_path = None
        _delete_announcement_image(old_image)
    else:
        image_path = old_image
    update_announcement(
        announcement_id=announcement_id,
        title=title,
        text=text,
        date_from=start,
        date_to=end,
        priority=priority,
        category=category or "info",
        is_pinned=bool(is_pinned),
        image_path=image_path,
    )
    logger.info("Объявление id=%d отредактировано через веб", announcement_id)
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.post("/admin/announcements/{announcement_id}/deactivate")
def deactivate_announcement_route(
    request: Request,
    announcement_id: int,
    csrf_token: str = Form(default=""),
    limit_ok: None = Depends(admin_rate_limit),
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
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Удаляет объявление."""
    require_csrf(request, csrf_token)
    ok = delete_announcement(announcement_id)
    logger.info("Удаление объявления id=%d: %s", announcement_id, "успех" if ok else "не найдено")
    return RedirectResponse(url="/admin/announcements", status_code=303)


def _read_content_file(filename: str) -> list[dict]:
    """Читает JSON-файл контента (quotes/holidays) как список словарей."""
    path = _DATA_DIR / filename
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except (OSError, json.JSONDecodeError):
        logger.error("Не удалось прочитать %s", path)
        return []


def _write_content_file(filename: str, records: list[dict]) -> None:
    """Атомарно сохраняет JSON-файл контента и инвалидирует кэш."""
    global _QUOTES_CACHE, _HOLIDAYS_CACHE
    path = _DATA_DIR / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    _QUOTES_CACHE = None
    _HOLIDAYS_CACHE = None


@router.get("/admin/content", response_class=HTMLResponse)
def admin_content(
    request: Request,
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Панель управления цитатами и праздниками."""
    session_id = get_session_id(request)
    csrf_token = generate_csrf_token(session_id)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "section": "content",
            "quotes": _read_content_file("quotes.json"),
            "holidays": _read_content_file("holidays.json"),
            "title": f"{settings.app_title} — Контент",
            "csrf_token": csrf_token,
        },
    )


@router.post("/admin/content/quotes/add")
def add_quote_route(
    request: Request,
    text: str = Form(...),
    author: str = Form(default=""),
    csrf_token: str = Form(default=""),
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Добавляет цитату в quotes.json."""
    require_csrf(request, csrf_token)
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Текст цитаты не может быть пустым")
    records = _read_content_file("quotes.json")
    records.append({"text": text, "author": author.strip()})
    _write_content_file("quotes.json", records)
    logger.info("Добавлена цитата через веб")
    return RedirectResponse(url="/admin/content", status_code=303)


@router.post("/admin/content/quotes/{idx}/delete")
def delete_quote_route(
    request: Request,
    idx: int,
    csrf_token: str = Form(default=""),
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Удаляет цитату по индексу."""
    require_csrf(request, csrf_token)
    records = _read_content_file("quotes.json")
    if not 0 <= idx < len(records):
        raise HTTPException(status_code=404, detail="Цитата не найдена")
    removed = records.pop(idx)
    _write_content_file("quotes.json", records)
    logger.info("Удалена цитата: %s", removed.get("text", "")[:40])
    return RedirectResponse(url="/admin/content", status_code=303)


@router.post("/admin/content/holidays/add")
def add_holiday_route(
    request: Request,
    holiday_date: str = Form(...),
    name: str = Form(...),
    greeting: str = Form(default="Праздник!"),
    emoji: str = Form(default="\U0001F389"),
    csrf_token: str = Form(default=""),
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Добавляет праздник в holidays.json."""
    require_csrf(request, csrf_token)
    holiday_date = holiday_date.strip()
    name = name.strip()
    if not re.fullmatch(r"\d{2}-\d{2}", holiday_date):
        raise HTTPException(status_code=400, detail="Дата праздника должна быть в формате ММ-ДД")
    if not name:
        raise HTTPException(status_code=400, detail="Название праздника не может быть пустым")
    records = _read_content_file("holidays.json")
    records.append({
        "date": holiday_date,
        "name": name,
        "greeting": greeting.strip() or "Праздник!",
        "emoji": emoji.strip() or "\U0001F389",
    })
    _write_content_file("holidays.json", records)
    logger.info("Добавлен праздник через веб: %s", name)
    return RedirectResponse(url="/admin/content", status_code=303)


@router.post("/admin/content/holidays/{idx}/delete")
def delete_holiday_route(
    request: Request,
    idx: int,
    csrf_token: str = Form(default=""),
    limit_ok: None = Depends(admin_rate_limit),
    _: None = Depends(verify_admin),
):
    """Удаляет праздник по индексу."""
    require_csrf(request, csrf_token)
    records = _read_content_file("holidays.json")
    if not 0 <= idx < len(records):
        raise HTTPException(status_code=404, detail="Праздник не найден")
    removed = records.pop(idx)
    _write_content_file("holidays.json", records)
    logger.info("Удалён праздник: %s", removed.get("name", "")[:40])
    return RedirectResponse(url="/admin/content", status_code=303)
