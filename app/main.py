"""Точка входа FastAPI приложения.

Инициализирует приложение, БД, планировщик и монтирует маршруты.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routes import router
from app.scheduler import check_birthdays, expire_old_announcements, setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управляет жизненным циклом приложения.

    При старте инициализирует БД и запускает планировщик.
    При остановке корректно завершает планировщик.
    """
    global scheduler
    logger.info("Запуск %s", settings.app_title)
    init_db()
    check_birthdays()
    expire_old_announcements()
    scheduler = setup_scheduler()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")


app = FastAPI(
    title=settings.app_title,
    lifespan=lifespan,
)

static_dir = Path("app") / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
else:
    logger.warning("Каталог static не найден: %s", static_dir)

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8800, reload=True)
