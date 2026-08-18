# Аудит проекта: Корпоративный информер для TV-мониторов

**Дата анализа:** 2026-08-18
**Стек:** FastAPI + SQLite + Jinja2 + Pillow + APScheduler
**Цель:** Оценка готовности к продакшну

---

## 1. Общая оценка

| Критерий | Оценка | Комментарий |
|---|---|---|
| **Архитектура** | 8/10 | Чистая, логичная структура. KISS на максимуме |
| **Безопасность** | 3/10 | Критические проблемы. Не готов к публичному доступу |
| **Качество кода** | 8/10 | Хорошие докстринги, понятная логика, типизация |
| **Производительность** | 6/10 | Есть узкие места (vinette, SQLite under load) |
| **Деплой** | 7/10 | Docker есть, но не хватает некоторых вещей |
| **Тестируемость** | 2/10 | Нет ни одного теста |
| **Итого** | **5.7/10** | **В продакшн МОЖНО, но с исправлениями** |

---

## 2. Архитектура и структура

### Сильные стороны

- **Разделение ответственности** — каждый модуль делает ровно одну вещь: `db.py` = данные, `routes.py` = HTTP, `image_gen.py` = Pillow, `weather.py` = API, `scheduler.py` = cron
- **Конфигурация через env** — `pydantic-settings` с префиксом `CORP_` — грамотный подход, всё настраивается без правки кода
- **Lifespan-контекст** — корректная инициализация/остановка в `main.py:28-43`
- **WAL-режим SQLite** — `PRAGMA journal_mode=WAL` в `db.py:30` — правильный выбор для чтения
- **Автоматические миграции** — `_run_migration()` в `db.py:53-67` — элегантное решение (хотя и наивное)
- **Кэширование погоды** — 15 минут, с fallback на старый кэш — продуманно

### Зоны риска

| Проблема | Файл | Строка | Критичность |
|---|---|---|---|
| SQLite + запись через контекстный менеджер с autocommit — при конкурентном доступе будет `database is locked` | `db.py:36-50` | Каждый запрос = новый `conn` | HIGH |
| `auto_deactivate_expired()` вызывается на каждом запросе к главной странице | `routes.py:120` | `_get_today_greetings()` | MEDIUM |
| Глобальный `scheduler = None` — не thread-safe | `main.py:25` | Глобальная переменная | LOW |
| Путь к БД относительный `data/corp_site.db` — зависит от CWD | `config.py:23` | Зависимость от рабочей директории | MEDIUM |

---

## 3. Безопасность — КРИТИЧЕСКИЕ ПРОБЛЕМЫ

### 3.1. Пароль admin/admin захардкожен

```python
# config.py:32-33
admin_username: str = "admin"
admin_password: str = "admin"
```

**Риск:** Любой, кто знает URL `/admin`, может зайти под `admin/admin`. В `.env` нет переменных `CORP_ADMIN_USERNAME` / `CORP_ADMIN_PASSWORD`.

**Решение:** Добавить в `.env` обязательные переменные с валидацией при первом запуске.

### 3.2. Basic Auth без HTTPS — пароль летит открытым текстом

```python
# routes.py:46
security = HTTPBasic(auto_error=False)
```

Basic Auth передаёт логин/пароль в заголовке `Authorization: Basic base64(...)`. Без HTTPS это **открытый текст**.

**Решение:** Минимум — добавить HTTPS (reverse proxy: nginx/caddy). Или заменить на session-based авторизацию.

### 3.3. XSS через Markdown

```python
# routes.py:76
return md_lib.markdown(text, extensions=["nl2br"])
```

В шаблоне:
```html
<!-- index.html:104 -->
<div class="ann-body">{{ item.text|markdown|safe }}</div>
```

Флаг `|safe` отключает экранирование. Если кто-то введёт `<script>alert(1)</script>` в объявление — он выполнится на всех TV-мониторах.

**Решение:** Использовать `bleach` для санитизации HTML после markdown:
```python
import bleach
ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'h1', 'h2', 'h3']
return bleach.clean(md_lib.markdown(text, extensions=["nl2br"]), tags=ALLOWED_TAGS)
```

### 3.4. Нет CSRF-защиты на POST-формах

Все формы в `admin.html` — обычные HTML POST-формы без CSRF-токена. Если злоумышленник создаст forged-форму на внешнем сайте, она может отправить запрос от имени залогиненного админа.

**Решение:** Добавить CSRF-токен через middleware или использовать `starlette-wtf`.

### 3.5. SQL-инъекции — нет

Параметризованные запросы (`?`) используются везде в `db.py`. Это **хорошо** — SQL-инъекций нет.

---

## 4. Производительность

### 4.1. Vignette — O(width × height) — КРИТИЧНО

```python
# image_gen.py:218-225
def _draw_vignette(draw, width, height):
    for x in range(width):
        for y in range(height):
            # 1920 × 1080 = 2,073,600 итераций
```

На каждом пикселе вызывается `draw.point()` — это **2+ миллиона** отдельных вызовов Pillow. На Raspberry Pi или при большом количестве именинников это будет работать **очень медленно** (до 30 сек на изображение).

**Решение:** Использовать `Image.alpha_composite` с предгенерированной виньеткой или numpy:
```python
import numpy as np
# Создать виньетку через numpy и наложить за O(1)
```

### 4.2. Конкурентный доступ к SQLite

Каждый HTTP-запрос создаёт новое подключение (`get_connection()` в `db.py:17`). При одновременных запросах (TV-монитор + админка + скрипт сидинга) будет конфликт `database is locked`.

**Решение:** Использовать пул соединений или `aiosqlite` для async-доступа.

### 4.3. `_draw_confetti` — `random.randint` на каждой итерации

```python
# image_gen.py:142-166
for _ in range(random.randint(20, 40)):
    x = random.randint(0, width)
    y = random.randint(0, height)
```

Не критично, но можно оптимизировать через `random.choices` + vectorized operations.

### 4.4. Погода: `urlopen` блокирует event loop

```python
# weather.py:58
with urlopen(url, timeout=10) as resp:
```

FastAPI — async, но `urlopen` — блокирующий вызов. На время запроса к Open-Meteo весь event loop冻结.

**Решение:** Использовать `httpx` + `async def` или выносить в `run_in_executor`.

---

## 5. Проблемы кода

### 5.1. Дублирование логики генерации имени файла

```python
# routes.py:98
safe_name = re.sub(r'[^\w\s-]', '', emp['name']).strip().replace(' ', '_')
greeting_name = f"greeting_{safe_name}.jpg"

# image_gen.py:396
safe_name = re.sub(r'[^\w\s-]', '', employee_name).strip().replace(' ', '_')
filename = f"greeting_{safe_name}.jpg"
```

Одна и та же логика в двух местах. Если изменится в одном — сломается в другом.

**Решение:** Вынести в общую функцию `make_greeting_filename(name: str) -> str`.

### 5.2. `_run_migration` — наивный подход

```python
# db.py:53-67
for sql in migrations:
    try:
        conn.execute(sql)
    except sqlite3.OperationalError:
        pass  # Молча проглатываем ошибки
```

Причины:
- `ALTER TABLE ADD COLUMN` в SQLite может падать по-разному
- Нет версионирования миграций
- Ошибки маскируются

**Решение:** Для продакшна — `alembic` или хотя бы проверка `PRAGMA table_info()` перед миграцией.

### 5.3. `seed_data.py` — SQL-инъекция через f-string

```python
# seed_data.py:24
conn.execute(f"DELETE FROM {table}")
```

Хотя `table` — hardcoded, это плохая практика. Если когда-то изменить источник таблиц — будет инъекция.

### 5.4. Два скрипта сидинга

- `seed_data.py` — 5 сотрудников
- `reset_and_seed.py` — 50 сотрудников + 50 объявлений

Запутанно. Непонятно, какой использовать.

### 5.5. `image_path` в `Announcement` — путь от пользователя

```python
# routes.py:287
image_path: str = Form(default="")
```

Пользователь вводит путь к изображению вручную. Может указать `../../etc/passwd` или внешний URL.

**Решение:** Валидировать пути: только `/static/greetings/...`, запретить `..`.

---

## 6. Docker и деплой

### 6.1. Dockerfile — хорошо, но можно лучше

```dockerfile
# Dockerfile:1-18
FROM python:3.12-slim
```

- Нет multi-stage build — образ тяжелее чем нужно
- Нет non-root user — контейнер запускается от root
- Нет healthcheck

### 6.2. docker-compose.yml — минимально

```yaml
# docker-compose.yml
services:
  corp-site:
    build: .
    ports:
      - "8800:8800"
    volumes:
      - ./data:/app/data
      - ./app/static/greetings:/app/app/static/greetings
```

Нет:
- `healthcheck`
- `logging` configuration
- `deploy.resources.limits` (ограничение памяти)
- `depends_on` (если будет нужна другая сервис)

### 6.3. volumes — дублирование путей

`./app/static/greetings:/app/app/static/greetings` — два уровня `app` выглядят подозрительно. Внутри контейнера путь `/app/app/static/greetings` — это баг или feature?

---

## 7. Тестирование

### Отсутствует полностью

- Нет `tests/` директории
- Нет `pytest.ini` / `pyproject.toml` с конфигурацией тестов
- Нет `conftest.py`
- Нет `requirements-dev.txt`

**Рекомендация:** Минимум — unit-тесты для `db.py`, `weather.py`, `image_gen.py`.

---

## 8. Чеклист: что исправить ДО продакшна

### КРИТИЧНО (must-fix)

- [ ] **Сменить admin/admin** — добавить `CORP_ADMIN_USERNAME` / `CORP_ADMIN_PASSWORD` в `.env` и валидировать
- [ ] **Санитизация Markdown** — добавить `bleach` или `nh3` для очистки HTML
- [ ] **HTTPS** — настроить reverse proxy (nginx/caddy) с TLS
- [ ] **CSRF-защита** — добавить токены на POST-формы
- [ ] **Vignette оптимизация** — заменить pixel-by-pixel на numpy/composite
- [ ] **Дать контейнеру non-root пользователя** в Dockerfile
- [ ] **Убрать `seed_data.py`** — оставить только `reset_and_seed.py`

### ВАЖНО (should-fix)

- [ ] **Пул соединений SQLite** или переход на `aiosqlite`
- [ ] **Вынести `urlopen`** из sync-контекста async FastAPI
- [ ] **Валидация `image_path`** — только относительные пути в `/static/greetings/`
- [ ] **Healthcheck endpoint** — `GET /health` для Docker и мониторинга
- [ ] **Логирование в файл** — `logging.handlers.RotatingFileHandler`
- [ ] **Добавить тесты** — минимум для CRUD операций
- [ ] **`pyproject.toml`** вместо `requirements.txt` — современный стандарт
- [ ] **Убрать глобальный `scheduler = None`** — использовать `app.state`

### ЖЕЛАТЕЛЬНО (nice-to-have)

- [ ] Multi-stage Dockerfile
- [ ] `deploy.resources.limits` в docker-compose
- [ ] Rate limiting на админ-эндпоинты
- [ ] Резервное копирование БД
- [ ] Prometheus метрики
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] pre-commit hooks (ruff, mypy)

---

## 9. Детальные рекомендации по коду

### 9.1. `config.py` — добавить валидацию

```python
class Settings(BaseSettings):
    admin_username: str = Field(..., min_length=1)  # Обязательный
    admin_password: str = Field(..., min_length=8)   # Минимум 8 символов

    @field_validator("admin_password")
    @classmethod
    def password_not_default(cls, v):
        if v == "admin":
            raise ValueError("Пароль 'admin' запрещён")
        return v
```

### 9.2. `weather.py` — async-версия

```python
import httpx

async def _fetch_forecast() -> list[dict] | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        data = resp.json()
    # ...
```

### 9.3. `image_gen.py` — оптимизация vignette

```python
import numpy as np
from PIL import Image

def _make_vignette_mask(width, height):
    """Создаёт маску виньетки через numpy — в 100+ раз быстрее."""
    y, x = np.ogrid[:height, :width]
    cx, cy = width / 2, height / 2
    dist = np.sqrt((x - cx)**2 + (y - cy)**2)
    max_dist = np.sqrt(cx**2 + cy**2)
    ratio = dist / max_dist
    alpha = np.clip((0.5 - ratio) * 200, 0, 200).astype(np.uint8)
    mask = Image.fromarray(alpha, 'L')
    return mask
```

### 9.4. `db.py` — connection pooling

```python
import threading
_local = threading.local()

def get_connection():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(settings.db_path))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn
```

---

## 10. Что сделано хорошо (для похвалы)

1. **Документация** — почти каждая функция имеет docstring с `Args/Returns/Raises`. Это rare для side-проектов
2. **Типизация** — `list[dict]`, `dict | None`, `int | None` — современный Python 3.10+
3. **Разделение статики** — `backgrounds/male`, `backgrounds/female` — логично
4. **Fallback для шрифтов** — `image_gen.py:60-69` — кросс-платформенность
5. **Кэширование погоды с fallback** — если API упал, показывается старый прогноз
6. **Автоматическая деактивация** — просроченные объявления отключаются
7. **Markdown в объявлениях** — гибкость форматирования
8. **Анимации в informer.html** — частицы, градиенты, shimmer — выглядит дорого
9. **Адаптивный дизайн** — `@media` запросы для разных размеров экрана

---

## 11. Итоговая рекомендация

Проект **архитектурно зрелый** и **написан качественно**. Для корпоративного TV-монитора в закрытой сети — **можно запускать прямо сейчас** с минимальными исправлениями:

1. Сменить пароль
2. Поставить HTTPS (nginx reverse proxy)
3. Оптимизировать vignette

Для публичного доступа — нужна полная проверка безопасности (раздел 8).

**Оценка: 7/10 для закрытой сети, 3/10 для публичного доступа.**

---

*Аудит проведён: big-pickle, 2026-08-18*
